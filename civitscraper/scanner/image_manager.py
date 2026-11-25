"""
Image manager for CivitScraper.

This module handles downloading and managing images for models.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from ..api.client import CivitAIClient
from .discovery import get_image_path, list_preview_files

logger = logging.getLogger(__name__)


class ImageManager:
    """
    Manager for model images.

    This class handles downloading and managing images for models.
    """

    def __init__(self, config: Dict[str, Any], api_client: CivitAIClient):
        """
        Initialize image manager.

        Args:
            config: Configuration dictionary
            api_client: CivitAI API client
        """
        self.config = config
        self.api_client = api_client

        # Get output configuration
        self.output_config = config.get("output", {})

        # Get dry run flag
        self.dry_run = config.get("dry_run", False)

    def download_images(
        self,
        file_path: str,
        metadata: Dict[str, Any],
        max_count: Optional[int] = None,
        force_refresh: bool = False,
    ) -> List[str]:
        """
        Download images for model.

        Args:
            file_path: Path to model file
            metadata: Model metadata
            max_count: Maximum number of images to download (overrides config)
            force_refresh: Whether to force refresh images

        Returns:
            Local paths of the model's previews (existing and newly downloaded)
        """
        # Get image configuration
        image_config = self.output_config.get("images", {})

        # Check if we should skip existing images
        skip_existing = self.config.get("skip_existing", False)

        # Determine max_count - use provided value or get from config
        if max_count is None:
            # Get max_count from config, default to None for no limit
            max_count = image_config.get("max_count", None)
            if max_count is not None:
                logger.debug(f"Using configured max_count limit: {max_count} for file: {file_path}")
            else:
                logger.debug(f"No image limit configured for file: {file_path}")

        # Clean up existing preview images if not in dry
        # run mode and we're not skipping existing files
        if not self.dry_run and (force_refresh or not skip_existing):
            self._clean_up_old_previews(file_path, max_count)
        else:
            # Only log if there are actually images to clean up
            if self._count_existing_previews(file_path) > 0:
                logger.info(
                    f"Dry run or skipping existing: Would not remove old "
                    f"preview images for {file_path}"
                )

        # Count existing preview images
        existing_count = self._count_existing_previews(file_path)

        # Only skip if we have existing previews AND they meet the max_count requirement
        if skip_existing and not force_refresh and existing_count > 0:
            if max_count is not None and existing_count >= max_count:
                logger.info(
                    f"Skipping image downloads - already have {existing_count} preview images"
                )
                return self._existing_preview_paths(file_path, max_count)
            logger.debug(
                f"Found {existing_count} existing previews, but less than max_count ({max_count})"
            )

        # Get all available images
        all_images = metadata.get("images", [])
        logger.debug(f"Found {len(all_images)} images")

        # We already counted existing previews above, no need to count again
        logger.debug(f"Working with {existing_count} existing preview images")

        # Handle different scenarios based on max_count
        if max_count is not None:
            if existing_count > max_count:
                # Need to remove excess images
                if not self.dry_run and (force_refresh or not skip_existing):
                    self._clean_up_old_previews(file_path, max_count)
                existing_count = max_count

            # For new models (no existing previews), always download regardless of skip_existing
            if existing_count == 0:
                images = all_images[:max_count]
                logger.debug(f"New model - will download {len(images)} images")
            # For existing models, check if we need more images
            elif existing_count < max_count and (force_refresh or not skip_existing):
                # Calculate how many more images we need
                remaining = max_count - existing_count
                # Get the next batch of images to download
                images = all_images[existing_count : existing_count + remaining]
                logger.debug(f"Will download {len(images)} additional images")
            else:
                images = []
                logger.debug("No additional images needed")
        else:
            # No max_count limit
            images = all_images[existing_count:]
            logger.debug(f"No limit - will download {len(images)} additional images")

        # Download images
        downloaded: List[str] = []
        total_count = len(images)
        for i, image in enumerate(images):
            path = self._download_single_image(
                file_path, image, i + existing_count, total_count, skip_existing
            )
            if path:
                downloaded.append(path)

        # All previews (existing + newly downloaded)
        if skip_existing and not force_refresh:
            all_paths = self._existing_preview_paths(file_path, max_count)
            all_paths.extend(p for p in downloaded if p not in all_paths)
            return all_paths

        return downloaded

    def _count_existing_previews(self, file_path: str) -> int:
        """
        Count existing numbered preview files for a model.

        Args:
            file_path: Path to model file

        Returns:
            Number of existing preview files
        """
        return len(list_preview_files(file_path, self.config))

    def _existing_preview_paths(self, file_path: str, max_count: Optional[int]) -> List[str]:
        """
        Paths of a model's numbered preview files, lowest index first.

        Args:
            file_path: Path to model file
            max_count: Maximum number of images

        Returns:
            Preview file paths
        """
        paths = [path for path, _, _ in list_preview_files(file_path, self.config)]
        return paths[:max_count] if max_count is not None else paths

    def _clean_up_old_previews(self, file_path: str, max_count: Optional[int] = None) -> None:
        """
        Remove preview files beyond max_count (all of them if max_count is None or 0).

        Only files following the numbered preview naming scheme are touched; anything
        else in the directory (e.g. leftovers from other tools) is left alone.

        Args:
            file_path: Path to model file
            max_count: Maximum number of images to keep
        """
        preview_files = [path for path, _, _ in list_preview_files(file_path, self.config)]
        if not preview_files:
            return

        keep = max_count if max_count else 0
        for path in preview_files[keep:]:
            try:
                os.remove(path)
                logger.debug(f"Removed preview image: {path}")
            except Exception as e:
                logger.warning(f"Failed to remove preview image {path}: {e}")

    def _download_single_image(
        self,
        file_path: str,
        image: Dict[str, Any],
        index: int,
        total_count: int,
        skip_existing: bool = False,
    ) -> Optional[str]:
        """
        Download a single image.

        Args:
            file_path: Path to model file
            image: Image data
            index: Image index
            total_count: Total number of images to download
            skip_existing: Whether to skip existing files

        Returns:
            Local path of the preview, or None if the download failed
        """
        image_url = image.get("url")
        if not image_url:
            return None

        ext = os.path.splitext(image_url)[1]

        # Use simple preview naming with index
        preview_index = index + 1
        image_path = get_image_path(file_path, self.config, f"preview{preview_index}", ext)

        # Check if the file (or the video it was renamed to) already exists
        if skip_existing and os.path.isfile(image_path):
            logger.debug(f"Skipping existing image at {image_path}")
            return image_path
        video_path = os.path.splitext(image_path)[0] + ".mp4"
        if skip_existing and os.path.isfile(video_path):
            logger.debug(f"Skipping existing video at {video_path}")
            return video_path

        if self.dry_run:
            logger.info(f"Dry run: Would download image {preview_index} to {image_path}")
            return image_path
        return self._perform_download(image_url, image_path, index, total_count)

    def _perform_download(
        self, image_url: str, image_path: str, index: int, total_count: int
    ) -> Optional[str]:
        """
        Perform the actual download of an image.

        Args:
            image_url: URL of the image
            image_path: Path to save the image
            index: Image index
            total_count: Total number of images to download

        Returns:
            Local path of the downloaded file (``.mp4`` for videos), or None on failure
        """
        os.makedirs(os.path.dirname(image_path), exist_ok=True)

        preview_index = index + 1
        logger.debug(f"Downloading image {preview_index}/{total_count}")
        success, content_type = self.api_client.download_image(image_url, image_path)

        if not success:
            logger.warning(f"Failed to download image {preview_index}/{total_count}")
            return None

        # A video served under an image URL is renamed to .mp4 (the pages look for it)
        is_video = bool(content_type and content_type.startswith("video/"))
        if is_video and not image_path.lower().endswith(".mp4"):
            new_path = os.path.splitext(image_path)[0] + ".mp4"
            try:
                os.rename(image_path, new_path)
                logger.info(
                    f"Renamed video file from {image_path} to {new_path} "
                    f"based on Content-Type: {content_type}"
                )
                image_path = new_path
            except Exception as e:
                logger.error(f"Failed to rename video file from {image_path} to {new_path}: {e}")

        return image_path

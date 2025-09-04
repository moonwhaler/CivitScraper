"""
Image manager for CivitScraper.

This module handles downloading and managing images for models.
"""

import glob
import logging
import os
import re
from typing import Any, Dict, List, Optional

from ..api.client import CivitAIClient
from .discovery import get_html_path, get_image_path

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
    ) -> List[Dict[str, Any]]:
        """
        Download images for model.

        Args:
            file_path: Path to model file
            metadata: Model metadata
            max_count: Maximum number of images to download (overrides config)
            force_refresh: Whether to force refresh images

        Returns:
            List of dictionaries with information about downloaded images
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

        # Get model directory
        model_dir = os.path.dirname(file_path)

        # Get model name
        model_name = os.path.splitext(os.path.basename(file_path))[0]

        # Clean up existing preview images if not in dry
        # run mode and we're not skipping existing files
        if not self.dry_run and (force_refresh or not skip_existing):
            self._clean_up_old_previews(model_dir, model_name, max_count)
        else:
            # Only log if there are actually images to clean up
            if self._count_existing_previews(model_dir, model_name) > 0:
                logger.info(
                    f"Dry run or skipping existing: Would not remove old preview images for {file_path}"
                )

        # Count existing preview images
        existing_count = self._count_existing_previews(model_dir, model_name)

        # Only skip if we have existing previews AND they meet the max_count requirement
        if skip_existing and not force_refresh and existing_count > 0:
            if max_count is not None and existing_count >= max_count:
                logger.info(
                    f"Skipping image downloads - already have {existing_count} preview images"
                )
                return self._get_existing_image_info(file_path, model_dir, model_name, max_count)
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
                    self._clean_up_old_previews(model_dir, model_name, max_count)
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
        downloaded_images = []
        total_count = len(images)
        for i, image in enumerate(images):
            image_info = self._download_single_image(
                file_path, image, i + existing_count, total_count, skip_existing
            )
            if image_info:
                downloaded_images.append(image_info)

        # Get info for all images (existing + newly downloaded)
        if skip_existing and not force_refresh:
            all_image_info = self._get_existing_image_info(
                file_path, model_dir, model_name, max_count
            )
            # Add any newly downloaded images that aren't already included
            for img in downloaded_images:
                if img not in all_image_info:
                    all_image_info.append(img)
            return all_image_info

        return downloaded_images

    def _count_existing_previews(self, model_dir: str, model_name: str) -> int:
        """
        Count existing preview files.

        Args:
            model_dir: Model directory
            model_name: Model name

        Returns:
            Number of existing preview files
        """
        # Check all possible preview file formats
        count = 0
        for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]:
            pattern = os.path.join(model_dir, f"{model_name}.preview*{ext}")
            count += len(glob.glob(pattern))
        return count

    def _get_existing_image_info(
        self, file_path: str, model_dir: str, model_name: str, max_count: Optional[int]
    ) -> List[Dict[str, Any]]:
        """
        Get image info for existing preview files.

        Args:
            file_path: Path to model file
            model_dir: Model directory
            model_name: Model name
            max_count: Maximum number of images

        Returns:
            List of image info dictionaries
        """
        # Get HTML path for relative path calculation
        html_path = get_html_path(file_path, self.config)
        html_dir = os.path.dirname(html_path)

        # Collect all preview files first
        preview_files = []
        for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]:
            pattern = os.path.join(model_dir, f"{model_name}.preview*{ext}")
            for image_path in glob.glob(pattern):
                preview_files.append((image_path, ext == ".mp4"))

        # Sort by preview number (lowest to highest)
        def extract_preview_number(filename: str) -> int:
            match = re.search(r"preview(\d+)", os.path.basename(filename))
            if not match:
                raise ValueError("Invalid preview filename")
            return int(match.group(1))

        preview_files.sort(key=lambda x: extract_preview_number(x[0]))

        # Take first max_count files
        if max_count is not None:
            preview_files = preview_files[:max_count]

        # Create info for each file
        result = []
        for image_path, is_video in preview_files:
            result.append(self._create_image_info(image_path, html_dir, {}, is_video))

        return result

    def _clean_up_old_previews(
        self, model_dir: str, model_name: str, max_count: Optional[int] = None
    ) -> None:
        """
        Clean up old preview images while respecting max_count.

        Args:
            model_dir: Model directory
            model_name: Model name
            max_count: Maximum number of images to keep
        """
        preview_files = []
        # Collect all preview files
        for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]:
            pattern = os.path.join(model_dir, f"{model_name}.preview*{ext}")
            preview_files.extend(glob.glob(pattern))

        if not preview_files:
            return

        # Sort by preview number (lowest to highest)
        def extract_preview_number(filename: str) -> int:
            match = re.search(r"preview(\d+)", os.path.basename(filename))
            if not match:
                raise ValueError("Invalid preview filename")
            return int(match.group(1))

        preview_files.sort(key=lambda x: extract_preview_number(x))

        if max_count is not None:
            if max_count > 0:
                # Remove all files after max_count
                files_to_remove = preview_files[max_count:]
                for file in files_to_remove:
                    try:
                        os.remove(file)
                        logger.debug(f"Removed excess preview image: {file}")
                    except Exception as e:
                        logger.warning(f"Failed to remove preview image {file}: {e}")
            else:
                # If max_count is 0, remove all files
                for file in preview_files:
                    try:
                        os.remove(file)
                        logger.debug(f"Removed preview image: {file}")
                    except Exception as e:
                        logger.warning(f"Failed to remove preview image {file}: {e}")
        else:
            # If no max_count, remove all files
            for file in preview_files:
                try:
                    os.remove(file)
                    logger.debug(f"Removed old preview image: {file}")
                except Exception as e:
                    logger.warning(f"Failed to remove preview image {file}: {e}")

    def _download_single_image(
        self,
        file_path: str,
        image: Dict[str, Any],
        index: int,
        total_count: int,
        skip_existing: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Download a single image.

        Args:
            file_path: Path to model file
            image: Image data
            index: Image index
            total_count: Total number of images to download
            skip_existing: Whether to skip existing files

        Returns:
            Dictionary with information about downloaded image, or None if download failed
        """
        # Get image URL
        image_url = image.get("url")
        if not image_url:
            return None

        # Get image extension
        ext = os.path.splitext(image_url)[1]

        # Use simple preview naming with index
        preview_index = index + 1
        image_path = get_image_path(file_path, self.config, f"preview{preview_index}", ext)

        # Get image metadata
        image_meta = image.get("meta", {})
        # Ensure image_meta is a dictionary, even if meta is None
        if image_meta is None:
            image_meta = {}

        # Get HTML path for relative path calculation
        html_path = get_html_path(file_path, self.config)
        html_dir = os.path.dirname(html_path)

        # Check if the file already exists and we're skipping existing files
        if skip_existing and os.path.isfile(image_path):
            logger.info(f"Skipping existing image at {image_path}")
            return self._create_image_info(image_path, html_dir, image_meta)

        # Check if a video version exists and we're skipping existing files
        video_path = os.path.splitext(image_path)[0] + ".mp4"
        if skip_existing and os.path.isfile(video_path):
            logger.info(f"Skipping existing video at {video_path}")
            return self._create_image_info(video_path, html_dir, image_meta, is_video=True)

        if self.dry_run:
            # Simulate download in dry run mode
            logger.info(f"Dry run: Would download image {preview_index} to {image_path}")
            # Add placeholder for dry run
            return self._create_image_info(image_path, html_dir, image_meta)
        else:
            return self._perform_download(
                image_url, image_path, html_dir, image_meta, index, total_count
            )

    def _perform_download(
        self,
        image_url: str,
        image_path: str,
        html_dir: str,
        image_meta: Dict[str, Any],
        index: int,
        total_count: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Perform the actual download of an image.

        Args:
            image_url: URL of the image
            image_path: Path to save the image
            html_dir: HTML directory for relative path calculation
            image_meta: Image metadata
            index: Image index
            total_count: Total number of images to download

        Returns:
            Dictionary with information about downloaded image, or None if download failed
        """
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(image_path), exist_ok=True)

        # Calculate preview index (1-based)
        preview_index = index + 1

        # Download image
        logger.debug(f"Downloading image {preview_index}/{total_count}")
        success, content_type = self.api_client.download_image(image_url, image_path)

        if not success:
            logger.warning(f"Failed to download image {preview_index}/{total_count}")
            return None

        # Check if the content type indicates a video
        is_video = bool(content_type and content_type.startswith("video/"))

        # If it's a video but has a wrong extension, save it with .mp4 extension
        if is_video and not image_path.lower().endswith(".mp4"):
            # Get the directory and filename without extension
            dir_name = os.path.dirname(image_path)
            base_name = os.path.splitext(os.path.basename(image_path))[0]

            # Create new path with .mp4 extension
            new_path = os.path.join(dir_name, f"{base_name}.mp4")

            # Rename the file
            try:
                os.rename(image_path, new_path)
                logger.info(
                    f"Renamed video file from {image_path} to {new_path} "
                    f"based on Content-Type: {content_type}"
                )
                # Update the image_path for further processing
                image_path = new_path
            except Exception as e:
                logger.error(f"Failed to rename video file from {image_path} to {new_path}: {e}")

        # Create and return image info
        return self._create_image_info(image_path, html_dir, image_meta, is_video)

    def _create_image_info(
        self, image_path: str, html_dir: str, image_meta: Dict[str, Any], is_video: bool = False
    ) -> Dict[str, Any]:
        """
        Create image information dictionary.

        Args:
            image_path: Path to image file
            html_dir: HTML directory for relative path calculation
            image_meta: Image metadata
            is_video: Whether the file is a video

        Returns:
            Dictionary with information about the image
        """
        # Calculate relative path from HTML to image
        rel_path = os.path.relpath(image_path, html_dir)

        # Create image info
        return {
            "path": rel_path,
            "prompt": image_meta.get("prompt", ""),
            "negative_prompt": image_meta.get("negativePrompt", ""),
            "sampler": image_meta.get("sampler", ""),
            "cfg_scale": image_meta.get("cfgScale", ""),
            "steps": image_meta.get("steps", ""),
            "seed": image_meta.get("seed", ""),
            "model": image_meta.get("Model", ""),
            "is_video": is_video,
        }

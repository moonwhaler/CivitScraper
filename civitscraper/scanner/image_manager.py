"""
Image manager for CivitScraper.

This module handles downloading and managing images for models.
"""

import glob
import logging
import os
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
        self, file_path: str, metadata: Dict[str, Any], max_count: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Download images for model.

        Args:
            file_path: Path to model file
            metadata: Model metadata
            max_count: Maximum number of images to download (overrides config)

        Returns:
            List of dictionaries with information about downloaded images
        """
        # Get image configuration
        image_config = self.output_config.get("images", {})

        # Determine max_count - use provided value or get from config
        if max_count is None:
            # Check if we're running the "fetch-all" job which uses the "full_process" template
            # We can determine this by checking if the output configuration has max_count=2
            if image_config.get("max_count") == 2:
                max_count = 2
                logger.debug(f"Using hard-coded max_count: {max_count} for file: {file_path}")
            else:
                max_count = image_config.get("max_count", 4)
                logger.debug(f"Using configured max_count: {max_count} for file: {file_path}")

        # Get model directory
        model_dir = os.path.dirname(file_path)

        # Get model name
        model_name = os.path.splitext(os.path.basename(file_path))[0]

        # Clean up existing preview images if not in dry run mode
        if not self.dry_run:
            self._clean_up_old_previews(model_dir, model_name)
        else:
            logger.info(f"Dry run: Would remove old preview images for {file_path}")

        # Get images
        images = metadata.get("images", [])

        # Log the number of images before limiting
        logger.debug(f"Number of images before limiting: {len(images)}")

        # Limit number of images
        images = images[:max_count]

        # Log the number of images after limiting
        logger.debug(f"Number of images after limiting to max_count {max_count}: {len(images)}")

        # Download images
        downloaded_images = []
        for i, image in enumerate(images):
            image_info = self._download_single_image(file_path, image, i)
            if image_info:
                downloaded_images.append(image_info)

        return downloaded_images

    def _clean_up_old_previews(self, model_dir: str, model_name: str) -> None:
        """
        Clean up old preview images.

        Args:
            model_dir: Model directory
            model_name: Model name
        """
        # Use a more comprehensive pattern to catch all preview files with any extension
        preview_pattern = os.path.join(model_dir, f"{model_name}.preview*.*")
        for old_image in glob.glob(preview_pattern):
            try:
                os.remove(old_image)
                logger.debug(f"Removed old preview image: {old_image}")
            except Exception as e:
                logger.warning(f"Failed to remove old preview image {old_image}: {e}")

    def _download_single_image(
        self, file_path: str, image: Dict[str, Any], index: int
    ) -> Optional[Dict[str, Any]]:
        """
        Download a single image.

        Args:
            file_path: Path to model file
            image: Image data
            index: Image index

        Returns:
            Dictionary with information about downloaded image, or None if download failed
        """
        # Get image URL
        image_url = image.get("url")
        if not image_url:
            return None

        # Get image extension
        ext = os.path.splitext(image_url)[1]

        # Get image path with explicit index in the image type
        # This ensures each image gets a unique filename
        image_path = get_image_path(file_path, self.config, f"preview{index}", ext)

        # Get image metadata
        image_meta = image.get("meta", {})
        # Ensure image_meta is a dictionary, even if meta is None
        if image_meta is None:
            image_meta = {}

        # Get HTML path for relative path calculation
        html_path = get_html_path(file_path, self.config)
        html_dir = os.path.dirname(html_path)

        # Check if the file already exists
        if os.path.isfile(image_path):
            return self._create_image_info(image_path, html_dir, image_meta)

        # Check if a video version exists
        video_path = os.path.splitext(image_path)[0] + ".mp4"
        if os.path.isfile(video_path):
            return self._create_image_info(video_path, html_dir, image_meta, is_video=True)

        if self.dry_run:
            # Simulate download in dry run mode
            logger.info(f"Dry run: Would download image {index+1} to {image_path}")
            # Add placeholder for dry run
            return self._create_image_info(image_path, html_dir, image_meta)
        else:
            return self._perform_download(
                image_url, image_path, html_dir, image_meta, index, len(image.get("images", []))
            )

    def _perform_download(
        self,
        image_url: str,
        image_path: str,
        html_dir: str,
        image_meta: Dict[str, Any],
        index: int,
        total_images: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Perform the actual download of an image.

        Args:
            image_url: URL of the image
            image_path: Path to save the image
            html_dir: HTML directory for relative path calculation
            image_meta: Image metadata
            index: Image index
            total_images: Total number of images

        Returns:
            Dictionary with information about downloaded image, or None if download failed
        """
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(image_path), exist_ok=True)

        # Download image
        logger.debug(f"Downloading image {index+1}/{total_images}")
        success, content_type = self.api_client.download_image(image_url, image_path)

        if not success:
            logger.warning(f"Failed to download image {index+1}/{total_images}")
            return None

        # Check if the content type indicates a video
        is_video = content_type and content_type.startswith("video/")

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
                    f"Renamed video file from {image_path} to {new_path} based on Content-Type: {content_type}"
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

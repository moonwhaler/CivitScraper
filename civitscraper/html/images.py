"""
Image handling utilities for HTML generation.

This module handles image discovery, processing, and metadata extraction.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from .paths import PathManager

logger = logging.getLogger(__name__)


class ImageHandler:
    """Handler for images used in HTML generation."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize image handler.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.path_manager = PathManager(config)

        # Get max_count from configuration, default to None for no limit
        self.max_count = self.config.get("output", {}).get("images", {}).get("max_count", None)

        self.dry_run = config.get("dry_run", False)

    def get_image_paths(self, file_path: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get the already-downloaded preview images of a model.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            List of image data dictionaries
        """
        return self._get_existing_images(file_path, metadata)

    def _get_existing_images(
        self, file_path: str, metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get existing images for a model.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            List of image data dictionaries
        """
        images = metadata.get("images", [])
        total_images = len(images)
        logger.debug(f"ImageHandler found {total_images} images")

        html_path = self.path_manager.get_html_path(file_path)
        html_dir = os.path.dirname(html_path)
        image_paths = []

        # Only process up to max_count images if set
        max_images = self.max_count if self.max_count is not None else total_images
        logger.debug(f"Processing up to {max_images} images based on configuration")

        # First, pre-filter images to avoid warnings for images beyond max_count
        images_to_process = images[:max_images] if max_images < total_images else images

        for i, image in enumerate(images_to_process):
            image_url = image.get("url")
            if not image_url:
                continue

            ext = os.path.splitext(image_url)[1]

            # Previews are downloaded with filenames that include the index number
            preview_index = i + 1
            image_path = self.path_manager.get_image_path(file_path, f"preview{preview_index}", ext)
            logger.debug(f"Looking for indexed image file ({preview_index}): {image_path}")

            if os.path.isfile(image_path):
                image_data = self._process_image(image_path, html_dir, image)
                if image_data:
                    image_paths.append(image_data)
            else:
                # If the indexed image file doesn't exist, check if a version with a different
                # extension exists. This handles the case where a video file was renamed from
                # .jpeg to .mp4 by the image manager
                base_path = os.path.splitext(image_path)[0]
                video_path = f"{base_path}.mp4"

                if os.path.isfile(video_path):
                    logger.debug(f"Found video file instead of image: {video_path}")
                    video_data = self._process_image(video_path, html_dir, image, is_video=True)
                    if video_data:
                        image_paths.append(video_data)
                elif os.path.isfile(image_path):
                    image_data = self._process_image(image_path, html_dir, image)
                    if image_data:
                        image_paths.append(image_data)
                else:
                    logger.debug(f"Image file not found: {image_path}")
                    # In dry run mode, we would normally download the image
                    if self.dry_run:
                        logger.info(
                            f"Dry run: Download {preview_index}/{len(images_to_process)} from "
                            f"{image.get('url')} to {image_path}"
                        )

        return image_paths

    def _process_image(
        self, image_path: str, html_dir: str, image: Dict[str, Any], is_video: Optional[bool] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Process image and extract metadata.

        Args:
            image_path: Path to image file
            html_dir: HTML directory for calculating relative paths
            image: Image metadata
            is_video: Whether the file is a video (if None, determined from extension)

        Returns:
            Image data dictionary or None if processing fails
        """
        try:
            image_meta = image.get("meta", {})
            # Ensure image_meta is a dictionary, even if meta is None
            if image_meta is None:
                image_meta = {}

            rel_path = os.path.relpath(image_path, html_dir)
            logger.debug(f"HTML dir: {html_dir}")
            logger.debug(f"Image path: {image_path}")
            logger.debug(f"Relative path: {rel_path}")

            # Determine if this is a video file based on extension if not explicitly provided
            if is_video is None:
                is_video = image_path.lower().endswith(".mp4")
            logger.debug(f"File is video: {is_video}")

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
        except Exception as e:
            logger.error(f"Error processing image {image_path}: {e}")
            return None

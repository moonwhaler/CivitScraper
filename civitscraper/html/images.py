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
    """
    Handler for images used in HTML generation.
    """

    def __init__(self, config: Dict[str, Any], model_processor=None):
        """
        Initialize image handler.

        Args:
            config: Configuration dictionary
            model_processor: ModelProcessor instance for downloading images (optional)
        """
        self.config = config
        self.model_processor = model_processor
        self.path_manager = PathManager(config)

        # For backward compatibility with the refactored code
        self.image_manager = None
        if model_processor and hasattr(model_processor, "image_manager"):
            self.image_manager = model_processor.image_manager

        # Get max_count from configuration
        self.max_count = self.config.get("output", {}).get("images", {}).get("max_count", 4)

        # Get dry run flag
        self.dry_run = config.get("dry_run", False)

    def get_image_paths(self, file_path: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get image paths for a model.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            List of image data dictionaries
        """
        # Log the max_count value for debugging
        logger.debug(f"ImageHandler using max_count: {self.max_count} for file: {file_path}")

        # Get image paths
        image_paths = []

        # If we have an ImageManager, use it to download images
        if self.image_manager:
            # Use the ImageManager to download images
            logger.debug(f"Using ImageManager to download images for {file_path}")
            image_paths = self.image_manager.download_images(file_path, metadata, self.max_count)
        # For backward compatibility, try using ModelProcessor if available
        elif self.model_processor and hasattr(self.model_processor, "download_images"):
            # Use the ModelProcessor to download images
            logger.debug(f"Using ModelProcessor to download images for {file_path}")
            image_paths = self.model_processor.download_images(file_path, metadata, self.max_count)
        else:
            # Fallback to checking for existing images
            logger.debug(
                f"No ModelProcessor available, checking for existing images for {file_path}"
            )
            image_paths = self._get_existing_images(file_path, metadata)

        return image_paths

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
        # Get model images
        images = metadata.get("images", [])

        # Log the number of images before limiting
        logger.debug(f"ImageHandler number of images before limiting: {len(images)}")

        # Limit number of images
        images = images[: self.max_count]

        # Log the number of images after limiting
        logger.debug(
            f"ImageHandler number of images after limiting to max_count {self.max_count}: {len(images)}"
        )

        # Get HTML path for calculating relative paths
        html_path = self.path_manager.get_html_path(file_path)
        html_dir = os.path.dirname(html_path)

        image_paths = []

        for i, image in enumerate(images):
            # Get image URL
            image_url = image.get("url")
            if not image_url:
                continue

            # Get image extension
            ext = os.path.splitext(image_url)[1]

            # Get the image path with the index number
            # The ModelProcessor downloads images with filenames that include the index number
            image_path = self.path_manager.get_image_path(file_path, f"preview{i}", ext)

            logger.debug(f"Looking for indexed image file ({i}): {image_path}")

            # Check if the indexed image file exists
            if os.path.isfile(image_path):
                # Process the image and add to list
                image_data = self._process_image(image_path, html_dir, image)
                if image_data:
                    image_paths.append(image_data)
            else:
                # If the indexed image file doesn't exist, check if a version with a different extension exists
                # This handles the case where a video file was renamed from .jpeg to .mp4 by the ModelProcessor

                # Get the base path without extension
                base_path = os.path.splitext(image_path)[0]

                # Check for common video extensions
                video_path = f"{base_path}.mp4"
                if os.path.isfile(video_path):
                    # Found a video file with the same base name
                    logger.debug(f"Found video file instead of image: {video_path}")

                    # Process the video and add to list
                    video_data = self._process_image(video_path, html_dir, image, is_video=True)
                    if video_data:
                        image_paths.append(video_data)
                # If no video file exists, check if the original image exists
                elif os.path.isfile(image_path):
                    # Process the image and add to list
                    image_data = self._process_image(image_path, html_dir, image)
                    if image_data:
                        image_paths.append(image_data)
                # If no image or video file exists, log a warning
                else:
                    logger.warning(f"Image file not found: {image_path}")
                    # In dry run mode, we would normally download the image
                    if self.dry_run:
                        logger.info(
                            f"Dry run: Would download image {i+1}/{len(images)} from {image.get('url')} to {image_path}"
                        )

        return image_paths

    def _process_image(
        self, image_path: str, html_dir: str, image: Dict[str, Any], is_video: bool = None
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
            # Get image metadata
            image_meta = image.get("meta", {})
            # Ensure image_meta is a dictionary, even if meta is None
            if image_meta is None:
                image_meta = {}

            # Calculate relative path from HTML to image
            rel_path = os.path.relpath(image_path, html_dir)

            # Log paths for debugging
            logger.debug(f"HTML dir: {html_dir}")
            logger.debug(f"Image path: {image_path}")
            logger.debug(f"Relative path: {rel_path}")

            # Determine if this is a video file based on extension if not explicitly provided
            if is_video is None:
                is_video = image_path.lower().endswith(".mp4")

            logger.debug(f"File is video: {is_video}")

            # Create image data dictionary
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

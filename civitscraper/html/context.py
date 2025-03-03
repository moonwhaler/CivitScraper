"""
Context preparation for HTML generation.

This module handles preparing context data for templates.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from .images import ImageHandler
from .paths import PathManager
from .sanitizer import DataSanitizer

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builder for template context."""

    def __init__(self, config: Dict[str, Any], model_processor=None):
        """
        Initialize context builder.

        Args:
            config: Configuration dictionary
            model_processor: ModelProcessor instance for downloading images (optional)
        """
        self.config = config
        self.model_processor = model_processor
        self.path_manager = PathManager(config)
        self.image_handler = ImageHandler(config, model_processor)
        self.sanitizer = DataSanitizer()

    def build_model_context(self, file_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build context for model template.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            Template context
        """
        # Get model information
        model_info = metadata.get("model", {})

        # Get model name - use the model name from metadata
        model_name = model_info.get("name", metadata.get("name", "Unknown"))

        # Get model type
        model_type = model_info.get("type", "Unknown")

        # Get model creator
        creator = model_info.get("creator", {}).get("username", "Unknown")

        # Get model description
        description = metadata.get("description", "")

        # Get model tags
        tags = model_info.get("tags", [])

        # Get model stats
        stats = metadata.get("stats", {})

        # Get image paths
        image_paths = self.image_handler.get_image_paths(file_path, metadata)

        # Sanitize and encode image data to avoid JSON parsing issues
        encoded_images = self.sanitizer.sanitize_json_data(image_paths)

        # Create context
        context = {
            "title": model_name,
            "model_name": model_name,
            "model_type": model_type,
            "creator": creator,
            "description": description,
            "tags": tags,
            "stats": stats,
            "images": image_paths,
            "images_encoded": encoded_images,
            "metadata": metadata,
        }

        return context

    def build_gallery_context(
        self, file_paths: List[str], title: str, output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build context for gallery template.

        Args:
            file_paths: List of model file paths or HTML file paths
            title: Gallery title
            output_path: Path to output HTML file (for relative path calculation)

        Returns:
            Template context
        """
        # Prepare context with explicit type annotations
        context: Dict[str, Any] = {
            "title": title,
            "models": [],  # Initialize as an empty list
            "output_path": output_path,
        }

        # Add models to context
        for file_path in file_paths:
            # Check if this is an HTML file or a model file
            is_html_file = file_path.lower().endswith(".html")

            # Get metadata path and HTML path based on file type
            if is_html_file:
                # For HTML files, the metadata file should be in the same directory with the same base name
                metadata_path = os.path.splitext(file_path)[0] + ".json"
                html_path = file_path  # The file is already an HTML file
                logger.debug(f"Processing existing HTML file: {file_path}")
            else:
                # For model files, get the metadata path and HTML path as before
                metadata_path = os.path.splitext(file_path)[0] + ".json"
                html_path = self.path_manager.get_html_path(file_path)
                logger.debug(f"Processing model file: {file_path}")

            # Check if metadata exists
            if not os.path.isfile(metadata_path):
                logger.warning(f"Metadata not found for {file_path}")
                continue

            # Load metadata
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except Exception as e:
                logger.error(f"Error loading metadata for {file_path}: {e}")
                continue

            # Calculate relative paths
            # If output_path is not provided, use the file_path's directory as reference
            output_dir = os.path.dirname(output_path) if output_path else os.path.dirname(file_path)
            html_rel_path = os.path.relpath(html_path, output_dir)

            # Log paths for debugging
            logger.debug(f"Gallery output dir: {output_dir}")
            logger.debug(f"HTML path: {html_path}")
            logger.debug(f"HTML relative path: {html_rel_path}")

            # Get base preview path without extension
            if is_html_file:
                # For HTML files, we need to determine the model file path to correctly find preview images
                # Assume model file has the same base name as the HTML file, just different extension
                html_dir = os.path.dirname(file_path)
                model_name = os.path.splitext(os.path.basename(file_path))[0]

                # Look for potential model files with common extensions
                model_file_path = None
                for ext in [".safetensors", ".ckpt", ".pt", ".bin"]:
                    potential_path = os.path.join(html_dir, model_name + ext)
                    if os.path.isfile(potential_path):
                        model_file_path = potential_path
                        break

                if model_file_path:
                    # Use the path manager with the actual model file path
                    logger.debug(f"Found model file for HTML: {model_file_path}")
                    base_preview_path = os.path.splitext(
                        self.path_manager.get_image_path(model_file_path, "preview0")
                    )[0]
                else:
                    # Fallback to simple naming scheme if model file not found
                    logger.debug("Model file not found for HTML, using fallback naming scheme")
                    base_preview_path = os.path.join(html_dir, f"{model_name}.preview0")
            else:
                # For model files, use the path manager
                base_preview_path = os.path.splitext(
                    self.path_manager.get_image_path(file_path, "preview0")
                )[0]

            # Try to find the preview image with any extension
            preview_rel_path = None

            # First try the base preview path
            for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]:
                preview_path = base_preview_path + ext
                if os.path.isfile(preview_path):
                    preview_rel_path = os.path.relpath(preview_path, output_dir)
                    logger.debug(f"Found preview image with base path: {preview_path}")
                    logger.debug(f"Preview relative path: {preview_rel_path}")
                    break

            # If nothing found and it's an HTML file, try a few more common patterns
            if is_html_file and preview_rel_path is None:
                html_dir = os.path.dirname(file_path)
                model_name = os.path.splitext(os.path.basename(file_path))[0]

                # Additional patterns to try
                additional_patterns = [
                    f"{model_name}_preview",  # No number suffix
                    f"{model_name}.preview",  # Different delimiter
                    f"{model_name}preview0",  # No delimiter
                    f"{model_name}-preview0",  # Different delimiter
                    f"{model_name}_image0",  # Different naming convention
                    f"{model_name}.image0",  # Different naming convention
                ]

                # Try each pattern with different extensions
                for pattern in additional_patterns:
                    for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]:
                        preview_path = os.path.join(html_dir, pattern + ext)
                        if os.path.isfile(preview_path):
                            preview_rel_path = os.path.relpath(preview_path, output_dir)
                            logger.debug(
                                f"Found preview image with alternative pattern: {preview_path}"
                            )
                            logger.debug(f"Preview relative path: {preview_rel_path}")
                            break
                    if preview_rel_path:
                        break

                # If still not found, check if there's an "images" directory and look there
                if preview_rel_path is None:
                    images_dir = os.path.join(html_dir, "images")
                    if os.path.isdir(images_dir):
                        logger.debug(f"Checking images directory: {images_dir}")
                        for filename in os.listdir(images_dir):
                            if model_name.lower() in filename.lower() and any(
                                filename.lower().endswith(ext)
                                for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]
                            ):
                                preview_path = os.path.join(images_dir, filename)
                                preview_rel_path = os.path.relpath(preview_path, output_dir)
                                logger.debug(
                                    f"Found preview image in images directory: {preview_path}"
                                )
                                break

                # If still no preview image found, check if there are any in the metadata
                if (
                    preview_rel_path is None
                    and "images" in metadata
                    and isinstance(metadata["images"], list)
                    and metadata["images"]
                ):
                    # Get the first image URL from metadata
                    for image in metadata["images"]:
                        if "url" in image and image["url"]:
                            preview_url = image["url"]
                            logger.debug(
                                f"Using image URL from metadata as fallback: {preview_url}"
                            )

                            # Check if we have a local copy of this image
                            image_filename = os.path.basename(preview_url)
                            local_path = os.path.join(html_dir, image_filename)
                            if os.path.isfile(local_path):
                                preview_rel_path = os.path.relpath(local_path, output_dir)
                                logger.debug(f"Found local copy of metadata image: {local_path}")
                                break

                            # If we don't have a local copy, just use the URL directly
                            # Note: This is a fallback and might not work if the URL is no longer accessible
                            preview_rel_path = preview_url
                            logger.debug(f"Using remote image URL directly: {preview_url}")
                            break

            # Check if the preview is a video
            is_video = False
            if preview_rel_path and preview_rel_path.lower().endswith(".mp4"):
                is_video = True
                logger.debug(f"Preview is video: {is_video}")

            # Add model to context
            # Ensure models is a list
            models_list = context.get("models", [])
            if not isinstance(models_list, list):
                models_list = []
                context["models"] = models_list

            # Get model stats
            stats = metadata.get("stats", {})
            download_count = stats.get("downloadCount", 0)
            rating = stats.get("rating", 0)
            rating_count = stats.get("ratingCount", 0)

            # Get model name - prefer model.name over version name if available
            model_name = metadata.get("model", {}).get("name") or metadata.get("name", "Unknown")

            # Now we can safely append with complete metadata
            models_list.append(
                {
                    "name": model_name,
                    "type": metadata.get("model", {}).get("type", "Unknown"),
                    "base_model": metadata.get("baseModel", "Unknown"),
                    "description": metadata.get("description", ""),
                    "html_path": html_rel_path,
                    "preview_image_path": preview_rel_path,
                    "is_video": is_video,
                    "stats": {
                        "downloads": download_count,
                        "rating": rating,
                        "rating_count": rating_count,
                    },
                    "created_at": metadata.get("createdAt"),
                    "updated_at": metadata.get("updatedAt"),
                    "version": metadata.get("name"),  # Version name
                    "model_id": metadata.get("modelId"),
                    "version_id": metadata.get("id"),
                }
            )

        return context

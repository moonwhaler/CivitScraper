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
            file_paths: List of model file paths
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
            # Get metadata path
            metadata_path = os.path.splitext(file_path)[0] + ".json"

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

            # Get HTML path
            html_path = self.path_manager.get_html_path(file_path)

            # Get preview image path
            preview_image_path = self.path_manager.get_image_path(file_path, "preview0")

            # Calculate relative paths
            # If output_path is not provided, use the file_path's directory as reference
            output_dir = os.path.dirname(output_path) if output_path else os.path.dirname(file_path)
            html_rel_path = os.path.relpath(html_path, output_dir)

            # Log paths for debugging
            logger.debug(f"Gallery output dir: {output_dir}")
            logger.debug(f"HTML path: {html_path}")
            logger.debug(f"HTML relative path: {html_rel_path}")

            preview_rel_path = None
            if os.path.isfile(preview_image_path):
                preview_rel_path = os.path.relpath(preview_image_path, output_dir)
                logger.debug(f"Preview image path: {preview_image_path}")
                logger.debug(f"Preview relative path: {preview_rel_path}")

            # Check if the preview is a video
            is_video = False
            if preview_rel_path and preview_image_path.lower().endswith(".mp4"):
                is_video = True
                logger.debug(f"Preview is video: {is_video}")

            # Add model to context
            # Ensure models is a list
            models_list = context.get("models", [])
            if not isinstance(models_list, list):
                models_list = []
                context["models"] = models_list

            # Now we can safely append
            models_list.append(
                {
                    "name": metadata.get("name", "Unknown"),
                    "type": metadata.get("model", {}).get("type", "Unknown"),
                    "creator": metadata.get("model", {})
                    .get("creator", {})
                    .get("username", "Unknown"),
                    "description": metadata.get("description", ""),
                    "html_path": html_rel_path,
                    "preview_image_path": preview_rel_path,
                    "is_video": is_video,
                }
            )

        return context

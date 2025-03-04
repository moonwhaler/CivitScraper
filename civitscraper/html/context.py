"""
Context preparation for HTML generation.

This module handles preparing context data for templates.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, TypedDict

from .images import ImageHandler
from .paths import PathManager
from .sanitizer import DataSanitizer


# Define a typed dictionary for the preview image result
class PreviewImageDict(TypedDict):
    """TypedDict representing a preview image with path and video flag."""

    path: str
    is_video: bool


# Type alias for the optional preview image result
PreviewImageResult = Optional[PreviewImageDict]

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
        context: Dict[str, Any] = {
            "title": title,
            "models": [],
            "output_path": output_path,
        }

        for file_path in file_paths:
            model_data = self._process_gallery_model(file_path, output_path)
            if model_data:
                context["models"].append(model_data)

        return context

    def _process_gallery_model(
        self, file_path: str, output_path: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Process a single model file for gallery context."""
        is_html_file = file_path.lower().endswith(".html")
        metadata_path = os.path.splitext(file_path)[0] + ".json"
        html_path = file_path if is_html_file else self.path_manager.get_html_path(file_path)

        # Check and load metadata
        metadata = self._load_metadata(metadata_path)
        if not metadata:
            return None

        # Calculate paths
        output_dir = os.path.dirname(output_path) if output_path else os.path.dirname(file_path)
        html_rel_path = os.path.relpath(html_path, output_dir)

        # Find preview image
        preview_image = self._find_preview_image(file_path, metadata, output_dir, is_html_file)
        preview_data: Dict[str, Any] = {
            "path": preview_image["path"] if preview_image else None,
            "is_video": preview_image["is_video"] if preview_image else False,
        }

        # Get model stats
        stats = metadata.get("stats", {})
        model_stats = {
            "downloads": stats.get("downloadCount", 0),
            "rating": stats.get("rating", 0),
            "rating_count": stats.get("ratingCount", 0),
        }

        # Get model name
        model_name = metadata.get("model", {}).get("name") or metadata.get("name", "Unknown")

        return {
            "name": model_name,
            "type": metadata.get("model", {}).get("type", "Unknown"),
            "base_model": metadata.get("baseModel", "Unknown"),
            "description": metadata.get("description", ""),
            "html_path": html_rel_path,
            "preview_image_path": preview_data.get("path"),
            "is_video": preview_data.get("is_video", False),
            "stats": model_stats,
            "created_at": metadata.get("createdAt"),
            "updated_at": metadata.get("updatedAt"),
            "version": metadata.get("name"),
            "model_id": metadata.get("modelId"),
            "version_id": metadata.get("id"),
        }

    def _load_metadata(self, metadata_path: str) -> Optional[Dict[str, Any]]:
        """Load metadata from a JSON file, checking both organized and original locations."""
        # First try the direct path
        if os.path.isfile(metadata_path):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata: Dict[str, Any] = json.load(f)
                    return metadata
            except Exception as e:
                logger.error(f"Error loading metadata from {metadata_path}: {e}")
                return None

        # If not found, check if this is an organized path or original path
        is_in_organized_dir = "/organized/" in metadata_path

        if is_in_organized_dir:
            # We have an organized path, try to find original
            try:
                # Extract the base filename from the organized path
                filename = os.path.basename(metadata_path)

                # Find the "models/" part of the path to extract base directory
                models_index = metadata_path.find("/models/")
                if models_index != -1:
                    # Extract model type (e.g., "Lora")
                    path_parts = metadata_path[models_index:].split("/")
                    if len(path_parts) >= 3:
                        original_dir = "/".join(path_parts[:3])
                        original_path = os.path.join(original_dir, filename)

                        if os.path.isfile(original_path):
                            try:
                                with open(original_path, "r", encoding="utf-8") as f:
                                    original_metadata: Dict[str, Any] = json.load(f)
                                    logger.debug(
                                        f"Found metadata in original location: {original_path}"
                                    )
                                    return original_metadata
                            except Exception as e:
                                logger.error(
                                    f"Error loading metadata from org path {original_path}: {e}"
                                )
            except Exception as e:
                logger.error(
                    f"Error trying to find original metadata path for {metadata_path}: {e}"
                )

        # If we got here, the metadata wasn't found in either location
        logger.warning(f"Metadata not found: {metadata_path}")
        return None

    def _find_preview_image(
        self, file_path: str, metadata: Dict[str, Any], output_dir: str, is_html_file: bool
    ) -> PreviewImageResult:
        """Find preview image for a model."""
        # Define the return type explicitly
        preview_result: PreviewImageResult = None

        # Try standard preview path first
        preview_path: PreviewImageResult = self._try_standard_preview_path(
            file_path, output_dir, is_html_file
        )
        if preview_path is not None:
            preview_result = preview_path
            return preview_result

        # Try alternative patterns for HTML files
        if is_html_file:
            alt_preview_path: PreviewImageResult = self._try_alternative_patterns(
                file_path, output_dir
            )
            if alt_preview_path is not None:
                preview_result = alt_preview_path
                return preview_result

            # Try images directory
            dir_preview_path: PreviewImageResult = self._try_images_directory(file_path, output_dir)
            if dir_preview_path is not None:
                preview_result = dir_preview_path
                return preview_result

            # Try metadata URLs as last resort
            metadata_preview_path: PreviewImageResult = self._try_metadata_urls(
                metadata, file_path, output_dir
            )
            preview_result = metadata_preview_path
            return preview_result

        return preview_result

    def _try_standard_preview_path(
        self, file_path: str, output_dir: str, is_html_file: bool
    ) -> PreviewImageResult:
        """Try finding preview image at standard path."""
        if is_html_file:
            model_file = self._find_model_file(file_path)
            base_preview_path = (
                os.path.splitext(self.path_manager.get_preview_path(model_file, 0))[0]
                if model_file
                else os.path.join(
                    os.path.dirname(file_path),
                    f"{os.path.splitext(os.path.basename(file_path))[0]}.preview0",
                )
            )
        else:
            base_preview_path = self.path_manager.get_preview_base_path(file_path)

        for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]:
            preview_path = base_preview_path + ext
            if os.path.isfile(preview_path):
                is_video = ext.lower() == ".mp4"
                result: PreviewImageDict = {
                    "path": os.path.relpath(preview_path, output_dir),
                    "is_video": is_video,
                }
                return result

        return None

    def _find_model_file(self, html_file: str) -> Optional[str]:
        """Find corresponding model file for an HTML file."""
        html_dir = os.path.dirname(html_file)
        model_name = os.path.splitext(os.path.basename(html_file))[0]

        for ext in [".safetensors", ".ckpt", ".pt", ".bin"]:
            potential_path = os.path.join(html_dir, model_name + ext)
            if os.path.isfile(potential_path):
                return potential_path

        return None

    def _try_alternative_patterns(self, file_path: str, output_dir: str) -> PreviewImageResult:
        """Try alternative naming patterns for preview images."""
        html_dir = os.path.dirname(file_path)
        model_name = os.path.splitext(os.path.basename(file_path))[0]

        patterns = [
            f"{model_name}_preview",
            f"{model_name}.preview",
            f"{model_name}preview0",
            f"{model_name}-preview0",
            f"{model_name}_image0",
            f"{model_name}.image0",
        ]

        for pattern in patterns:
            for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]:
                preview_path = os.path.join(html_dir, pattern + ext)
                if os.path.isfile(preview_path):
                    is_video = ext.lower() == ".mp4"
                    result: PreviewImageDict = {
                        "path": os.path.relpath(preview_path, output_dir),
                        "is_video": is_video,
                    }
                    return result

        return None

    def _try_images_directory(self, file_path: str, output_dir: str) -> PreviewImageResult:
        """Try finding preview image in images directory."""
        html_dir = os.path.dirname(file_path)
        model_name = os.path.splitext(os.path.basename(file_path))[0]
        images_dir = os.path.join(html_dir, "images")

        if os.path.isdir(images_dir):
            for filename in os.listdir(images_dir):
                if model_name.lower() in filename.lower():
                    preview_path = os.path.join(images_dir, filename)
                    is_video = filename.lower().endswith(".mp4")
                    result: PreviewImageDict = {
                        "path": os.path.relpath(preview_path, output_dir),
                        "is_video": is_video,
                    }
                    return result

        return None

    def _try_metadata_urls(
        self, metadata: Dict[str, Any], file_path: str, output_dir: str
    ) -> PreviewImageResult:
        """Try using image URLs from metadata."""
        if not (
            "images" in metadata and isinstance(metadata["images"], list) and metadata["images"]
        ):
            return None

        for image in metadata["images"]:
            if "url" in image and image["url"]:
                preview_url = image["url"]
                image_filename = os.path.basename(preview_url)
                local_path = os.path.join(os.path.dirname(file_path), image_filename)

                if os.path.isfile(local_path):
                    is_video = local_path.lower().endswith(".mp4")
                    local_result: PreviewImageDict = {
                        "path": os.path.relpath(local_path, output_dir),
                        "is_video": is_video,
                    }
                    return local_result

                # Use remote URL as last resort
                is_video = preview_url.lower().endswith(".mp4")
                if preview_url:
                    remote_result: PreviewImageDict = {"path": preview_url, "is_video": is_video}
                    return remote_result
                return None

        return None

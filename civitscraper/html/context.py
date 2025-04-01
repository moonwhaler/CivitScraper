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
        model_info = metadata.get("model", {})
        model_name = model_info.get("name", metadata.get("name", "Unknown"))
        model_type = model_info.get("type", "Unknown")
        creator = model_info.get("creator", {}).get("username", "Unknown")
        description = metadata.get("description", "")
        tags = model_info.get("tags", [])
        stats = metadata.get("stats", {})
        image_paths = self.image_handler.get_image_paths(file_path, metadata)

        # Sanitize and encode image data to avoid JSON parsing issues
        encoded_images = self.sanitizer.sanitize_json_data(image_paths)

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

        metadata = self._load_metadata(metadata_path)
        if not metadata:
            return None

        output_dir = os.path.dirname(output_path) if output_path else os.path.dirname(file_path)
        # Use absolute path for the model's HTML file
        html_abs_path = os.path.abspath(html_path)

        preview_image = self._find_preview_image(file_path, metadata, output_dir, is_html_file)
        preview_data: Dict[str, Any] = {
            "path": preview_image["path"] if preview_image else None,
            "is_video": preview_image["is_video"] if preview_image else False,
        }

        stats = metadata.get("stats", {})
        model_stats = {
            "downloads": stats.get("downloadCount", 0),
            "rating": stats.get("rating", 0),
            "rating_count": stats.get("ratingCount", 0),
        }

        model_name = metadata.get("model", {}).get("name") or metadata.get("name", "Unknown")

        return {
            "name": model_name,
            "type": metadata.get("model", {}).get("type", "Unknown"),
            "base_model": metadata.get("baseModel", "Unknown"),
            "description": metadata.get("description", ""),
            "html_path": html_abs_path,  # Use absolute path
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

        # If metadata not found at direct path, try alternative paths
        try:
            filename = os.path.basename(metadata_path)
            is_in_organized_dir = "/organized/" in metadata_path

            if is_in_organized_dir:
                # We're in an organized directory, try to find the original
                organized_idx = metadata_path.find("/organized/")
                if organized_idx != -1:
                    original_base = metadata_path[:organized_idx]
                    original_path = os.path.join(original_base, filename)

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
                                f"Error loading metadata from original path {original_path}: {e}"
                            )
            else:
                # We're in an original path, try to find organized version
                # This handles the case where HTML files may have been left in the original location
                # but metadata was moved to organized locations
                organized_idx = metadata_path.rfind("/")
                if organized_idx != -1:
                    parent_dir = metadata_path[:organized_idx]
                    organized_dir = os.path.join(parent_dir, "organized")

                    if os.path.isdir(organized_dir):
                        for root, _, files in os.walk(organized_dir):
                            organized_path = os.path.join(root, filename)
                            if os.path.isfile(organized_path):
                                try:
                                    with open(organized_path, "r", encoding="utf-8") as f:
                                        organized_metadata: Dict[str, Any] = json.load(f)
                                        logger.debug(
                                            f"Found metadata in new location: {organized_path}"
                                        )
                                        return organized_metadata
                                except Exception as e:
                                    logger.error(
                                        f"Error loading metadata from path {organized_path}: {e}"
                                    )
                                break

        except Exception as e:
            logger.error(f"Error trying to find alternative metadata path for {metadata_path}: {e}")

        # If we got here, the metadata wasn't found in any location
        logger.warning(f"Metadata not found: {metadata_path}")
        return None

    def _find_preview_image(
        self, file_path: str, metadata: Dict[str, Any], output_dir: str, is_html_file: bool
    ) -> PreviewImageResult:
        """Find preview image for a model."""
        is_organized = "/organized/" in file_path

        # If this is an HTML file in the original location, try to find its organized version first
        if is_html_file and not is_organized:
            organized_path = self._find_organized_version(file_path)
            if organized_path:
                organized_preview = self._try_standard_preview_path(
                    organized_path, output_dir, is_html_file
                )
                if organized_preview is not None:
                    return organized_preview

        preview_path = self._try_standard_preview_path(file_path, output_dir, is_html_file)
        if preview_path is not None:
            return preview_path

        # For HTML files, try additional locations
        if is_html_file:
            alt_preview_path = self._try_alternative_patterns(file_path, output_dir)
            if alt_preview_path is not None:
                return alt_preview_path

            dir_preview_path = self._try_images_directory(file_path, output_dir)
            if dir_preview_path is not None:
                return dir_preview_path

            metadata_preview_path = self._try_metadata_urls(metadata, file_path, output_dir)
            if metadata_preview_path is not None:
                return metadata_preview_path

        return None

    def _find_organized_version(self, file_path: str) -> Optional[str]:
        """Find organized version of a file."""
        base_dir = file_path
        while "/models/" in base_dir:
            base_dir = os.path.dirname(base_dir)

        if not base_dir:
            return None

        model_name = os.path.splitext(os.path.basename(file_path))[0]

        organized_base = os.path.join(base_dir, "organized")
        if not os.path.isdir(organized_base):
            return None

        for root, _, files in os.walk(organized_base):
            for filename in files:
                if filename == f"{model_name}.html":
                    return os.path.join(root, filename)

        return None

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
                    "path": os.path.abspath(preview_path),  # Use absolute path
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
                        "path": os.path.abspath(preview_path),  # Use absolute path
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
                        "path": os.path.abspath(preview_path),  # Use absolute path
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
                is_video = preview_url.lower().endswith(".mp4")
                ext = ".mp4" if is_video else ".jpg"

                # Try to find local file using preview index pattern
                logger.debug(f"Searching for preview files with indices 0-4 for {file_path}")

                # Check both original and organized locations
                paths_to_check = [file_path]
                if "/organized/" not in file_path:
                    # If we're in the original location, also check organized
                    organized_path = self._find_organized_version(file_path)
                    if organized_path:
                        paths_to_check.append(organized_path)
                        logger.debug(f"Also checking organized path: {organized_path}")

                for check_path in paths_to_check:
                    # Try preview index pattern
                    for i in range(5):  # Check first 5 preview indices
                        preview_path = self.path_manager.get_image_path(
                            check_path, f"preview{i}", ext
                        )
                        logger.debug(f"Checking for local file ({i}): {preview_path}")

                        if os.path.isfile(preview_path):
                            logger.debug(f"Found local preview file: {preview_path}")
                            preview_result: PreviewImageDict = {
                                "path": os.path.abspath(preview_path),  # Use absolute path
                                "is_video": is_video,
                            }
                            return preview_result

                    # Try the original downloaded file name
                    image_filename = os.path.basename(preview_url)
                    local_path = os.path.join(os.path.dirname(check_path), image_filename)
                    logger.debug(f"Checking for original file: {local_path}")

                    if os.path.isfile(local_path):
                        logger.debug(f"Found original file: {local_path}")
                        original_result: PreviewImageDict = {
                            "path": os.path.abspath(local_path),  # Use absolute path
                            "is_video": is_video,
                        }
                        return original_result

                logger.debug("No local files found in original or organized locations")

                # Use remote URL as last resort
                logger.debug(f"No local file found, using remote URL: {preview_url}")
                logger.debug(f"Checking file_path directory: {os.path.dirname(file_path)}")
                logger.debug(f"Directory contents: {os.listdir(os.path.dirname(file_path))}")

                # For CivitAI URLs, handle width parameter
                if preview_url and "image.civitai.com" in preview_url:
                    # Extract the width parameter if it exists
                    import re

                    width_match = re.search(r"width=(\d+)", preview_url)
                    width = width_match.group(1) if width_match else "450"

                    # Reconstruct URL based on file type
                    base_url = preview_url.split("width=")[0]
                    if is_video:
                        # For videos, only add width parameter
                        preview_url = f"{base_url}width={width}/" f"{os.path.basename(preview_url)}"
                    else:
                        # For images, include format=preview
                        preview_url = (
                            f"{base_url}format=preview/"
                            f"width={width}/"
                            f"{os.path.basename(preview_url)}"
                        )

                remote_result: PreviewImageDict = {"path": preview_url, "is_video": is_video}
                return remote_result

        return None

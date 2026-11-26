"""
Image handling utilities for HTML generation.

This module handles image discovery, processing, and metadata extraction.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from ..api.domains import get_domain_settings
from ..scanner.discovery import list_preview_files
from .paths import PathManager, relative_to

logger = logging.getLogger(__name__)


# CivitAI image meta keys -> A1111/Forge infotext labels, in infotext order.
# Size is built from width/height. Several keys have two spellings in the wild.
_INFOTEXT_KEYS: List[Tuple[str, Tuple[str, ...]]] = [
    ("Steps", ("steps",)),
    ("Sampler", ("sampler",)),
    ("Schedule type", ("Schedule type", "scheduler")),
    ("CFG scale", ("cfgScale",)),
    ("Seed", ("seed",)),
    ("Size", ()),
    ("Model hash", ("Model hash",)),
    ("Model", ("Model",)),
    ("Denoising strength", ("Denoising strength", "denoise")),
    ("Clip skip", ("clipSkip", "Clip skip")),
    ("Hires upscale", ("Hires upscale",)),
    ("Hires steps", ("Hires steps",)),
    ("Hires upscaler", ("Hires upscaler",)),
    ("RNG", ("RNG",)),
]


def image_is_nsfw(image: Dict[str, Any], threshold: int) -> bool:
    """
    Whether a preview image is NSFW.

    The image's ``nsfwLevel`` decides; entries without one (older sidecars filled
    from the NSFW image feed) carry a boolean ``nsfw`` instead.
    """
    level = image.get("nsfwLevel")
    if isinstance(level, (int, float)) and not isinstance(level, bool):
        return level >= threshold
    return bool(image.get("nsfw"))


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def generation_params(meta: Dict[str, Any]) -> List[List[str]]:
    """
    Return a preview image's generation settings as ordered (label, value) pairs.

    Labels follow the A1111/Forge infotext ("Steps", "CFG scale", "Size", ...),
    so the page can rebuild text that Forge's "Read generation parameters" parses.
    Nested values (dicts, lists) are skipped.
    """
    params: List[List[str]] = []
    for label, keys in _INFOTEXT_KEYS:
        if label == "Size":
            width, height = _positive_int(meta.get("width")), _positive_int(meta.get("height"))
            if width and height:
                params.append([label, f"{width}x{height}"])
            continue
        for key in keys:
            value = meta.get(key)
            if value is None or value == "" or isinstance(value, (dict, list)):
                continue
            params.append([label, str(value)])
            break
    return params


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
        _, self.nsfw_threshold, _ = get_domain_settings(config)

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
        Get the downloaded previews of a model with their image data.

        ``images[i]`` of the sidecar belongs to the preview file numbered ``i + 1``
        (any extension: a video may have been renamed to ``.mp4``). ``max_count``
        limits the current CivitAI images; archived previews (no longer on CivitAI,
        kept on disk) are always shown, after the current ones.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            List of image data dictionaries, current first
        """
        images = metadata.get("images") or []
        html_dir = os.path.dirname(self.path_manager.get_html_path(file_path))

        # First file per preview number
        files: Dict[int, Tuple[str, bool]] = {}
        for path, index, is_video in list_preview_files(file_path, self.config):
            files.setdefault(index, (path, is_video))

        current: List[Dict[str, Any]] = []
        archived: List[Dict[str, Any]] = []
        for i, image in enumerate(images):
            if not isinstance(image, dict):
                continue
            is_archived = bool(image.get("civitscraperArchived"))
            if not is_archived and self.max_count is not None and len(current) >= self.max_count:
                continue
            found = files.get(i + 1)
            if not found:
                logger.debug(f"Preview {i + 1} of {file_path} is not on disk")
                continue
            data = self._process_image(found[0], html_dir, image, is_video=found[1])
            if data:
                (archived if is_archived else current).append(data)
        return current + archived

    def _process_image(
        self, image_path: str, html_dir: str, image: Dict[str, Any], is_video: Optional[bool] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Return a preview's page data.

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

            # Determine if this is a video file based on extension if not explicitly provided
            if is_video is None:
                is_video = image_path.lower().endswith(".mp4")

            # Exactly what model.html and model.js read; settings travel in "params".
            return {
                "path": relative_to(image_path, html_dir),
                "prompt": str(image_meta.get("prompt") or ""),
                "negative_prompt": str(image_meta.get("negativePrompt") or ""),
                "params": generation_params(image_meta),
                "width": _positive_int(image.get("width")),
                "height": _positive_int(image.get("height")),
                "nsfw": image_is_nsfw(image, self.nsfw_threshold),
                "archived": bool(image.get("civitscraperArchived")),
                "is_video": is_video,
            }
        except Exception as e:
            logger.error(f"Error processing image {image_path}: {e}")
            return None

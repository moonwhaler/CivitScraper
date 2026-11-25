"""
Path utilities for HTML generation.

This module handles path-related functionality for HTML generation.
"""

import logging
import os
from typing import Any, Dict

from ..scanner.discovery import get_html_path, get_image_path

logger = logging.getLogger(__name__)

# Where the gallery goes when a job sets no output.metadata.html.gallery_path
# (relative to the working directory). Model pages link to the same place.
DEFAULT_GALLERY_PATH = "gallery.html"


def relative_to(path: str, directory: str) -> str:
    """``path`` relative to ``directory`` with forward slashes; absolute on another drive."""
    absolute = os.path.abspath(path)
    try:
        return os.path.relpath(absolute, directory).replace(os.sep, "/")
    except ValueError:
        return absolute


class PathManager:
    """
    Manager for HTML and image paths.

    This class extends the path-related functions from scanner.discovery with
    additional utilities for HTML generation.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize path manager.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        # Import discovery functions directly
        self.get_html_path = lambda file_path: get_html_path(file_path, self.config)
        self.get_image_path = lambda file_path, image_type="preview", ext=".jpg": get_image_path(
            file_path, self.config, image_type, ext
        )

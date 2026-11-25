"""
Path utilities for HTML generation.

This module handles path-related functionality for HTML generation.
"""

import logging
from typing import Any, Dict

from ..scanner.discovery import get_html_path, get_image_path

logger = logging.getLogger(__name__)


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

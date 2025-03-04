"""
Path utilities for HTML generation.

This module handles path-related functionality for HTML generation.
"""

import logging
import os
from typing import Any, Dict

from ..scanner.discovery import get_html_path, get_image_path, get_model_type

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
        self.get_model_type = lambda file_path: get_model_type(file_path, self.config)

    def get_relative_path(self, target_path: str, reference_path: str) -> str:
        """
        Calculate relative path from reference path to target path.

        Args:
            target_path: Target path
            reference_path: Reference path

        Returns:
            Relative path
        """
        reference_dir = os.path.dirname(reference_path)
        return os.path.relpath(target_path, reference_dir)

    def get_preview_path(self, file_path: str, index: int = 1, ext: str = ".jpg") -> str:
        """
        Get preview image path with index.

        Args:
            file_path: Path to model file
            index: Preview index number
            ext: Image file extension

        Returns:
            Path to preview image file
        """
        return self.get_image_path(file_path, f"preview{index}", ext)

    def get_preview_base_path(self, file_path: str, index: int = 1) -> str:
        """
        Get base preview path without extension.

        Args:
            file_path: Path to model file
            index: Preview index number

        Returns:
            Base path for preview image file (without extension)
        """
        return os.path.splitext(self.get_preview_path(file_path, index))[0]

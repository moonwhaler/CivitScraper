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

    This class provides a wrapper around the path-related functions in the
    scanner.discovery module to maintain compatibility with the rest of the
    codebase while providing a cleaner interface for the HTML generator.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize path manager.

        Args:
            config: Configuration dictionary
        """
        self.config = config

    def get_html_path(self, file_path: str) -> str:
        """
        Get HTML file path for model file.

        Args:
            file_path: Path to model file

        Returns:
            Path to HTML file
        """
        return get_html_path(file_path, self.config)

    def get_image_path(self, file_path: str, image_type: str = "preview", ext: str = ".jpg") -> str:
        """
        Get image file path for model file.

        Args:
            file_path: Path to model file
            image_type: Image type (e.g., preview, preview0, preview1, etc.)
            ext: Image file extension

        Returns:
            Path to image file
        """
        return get_image_path(file_path, self.config, image_type, ext)

    def get_relative_path(self, target_path: str, reference_path: str) -> str:
        """
        Calculate relative path from reference path to target path.

        Args:
            target_path: Target path
            reference_path: Reference path

        Returns:
            Relative path
        """
        # Get reference directory
        reference_dir = os.path.dirname(reference_path)

        # Calculate relative path
        return os.path.relpath(target_path, reference_dir)

    def get_model_type(self, file_path: str) -> str:
        """
        Get model type for file.

        Args:
            file_path: Path to model file

        Returns:
            Model type
        """
        return get_model_type(file_path, self.config)

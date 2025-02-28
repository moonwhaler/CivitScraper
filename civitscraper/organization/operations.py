"""
File operations for organization.

This module handles file operations (copy, move, symlink) for the organization feature.
"""

import logging
import os
import shutil
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class FileOperationHandler:
    """Handler for file operations (copy, move, symlink)."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize file operation handler.

        Args:
            config: Configuration dictionary
        """
        self.config = config

    def get_related_files(self, file_path: str) -> List[Tuple[str, str]]:
        """
        Get related files (metadata, HTML, previews) for a model file.

        Args:
            file_path: Path to model file

        Returns:
            List of (file_path, file_type) tuples
        """
        related_files = []
        base_path = os.path.splitext(file_path)[0]

        # Add metadata file
        metadata_path = f"{base_path}.json"
        if os.path.isfile(metadata_path):
            related_files.append((metadata_path, "metadata"))

        # Add HTML file
        html_path = f"{base_path}.html"
        if os.path.isfile(html_path):
            related_files.append((html_path, "html"))

        # Add preview images
        # Get max_count from configuration to know how many preview images to look for
        max_count = self.config.get("output", {}).get("images", {}).get("max_count", 4)

        # Check for indexed preview images (preview0.jpeg, preview1.jpeg, etc.)
        for i in range(max_count):
            for ext in [".jpeg", ".jpg", ".png"]:
                preview_path = f"{base_path}.preview{i}{ext}"
                if os.path.isfile(preview_path):
                    related_files.append((preview_path, f"preview{i}"))

        # Check for legacy non-indexed format (preview.jpg)
        legacy_preview_path = f"{base_path}.preview.jpg"
        if os.path.isfile(legacy_preview_path):
            related_files.append((legacy_preview_path, "preview"))

        return related_files

    def perform_operation(
        self, source_path: str, target_path: str, operation_type: str, dry_run: bool
    ) -> bool:
        """
        Perform a file operation (copy, move, symlink).

        Args:
            source_path: Source file path
            target_path: Target file path
            operation_type: Operation type ("copy", "move", "symlink")
            dry_run: If True, simulate operation without making changes

        Returns:
            True if operation was successful, False otherwise
        """
        try:
            # Create target directory if it doesn't exist
            target_dir = os.path.dirname(target_path)
            if not dry_run:
                os.makedirs(target_dir, exist_ok=True)

            # Perform operation
            if dry_run:
                logger.info(f"Dry run: Would {operation_type} {source_path} to {target_path}")
                return True

            if operation_type == "move":
                logger.info(f"Moving {source_path} to {target_path}")
                shutil.move(source_path, target_path)
            elif operation_type == "symlink":
                logger.info(f"Creating symlink from {source_path} to {target_path}")
                os.symlink(os.path.abspath(source_path), target_path)
            else:  # copy
                logger.info(f"Copying {source_path} to {target_path}")
                shutil.copy2(source_path, target_path)

            return True

        except Exception as e:
            logger.error(
                f"Error performing {operation_type} operation from {source_path} to "
                f"{target_path}: {e}"
            )
            return False

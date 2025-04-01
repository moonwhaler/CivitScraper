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

        # Add preview files using comprehensive pattern matching
        # Support up to 10 preview images with various extensions
        for i in range(10):
            for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]:
                preview_path = f"{base_path}.preview{i}{ext}"
                if os.path.isfile(preview_path):
                    related_files.append((preview_path, "preview"))

        return related_files

    def perform_operation(
        self,
        source_path: str,
        target_path: str,
        operation_type: str,
        on_collision: str,
        dry_run: bool,
    ) -> bool:
        """
        Perform a file operation (copy, move, symlink) with collision handling.

        Args:
            source_path: Source file path
            target_path: Target file path
            operation_type: Operation type ("copy", "move", "symlink")
            on_collision: Collision handling mode ("skip", "overwrite", "fail")
            dry_run: If True, simulate operation without making changes

        Returns:
            True if operation was successful or handled (e.g., skipped), False otherwise
        """
        target_exists = os.path.exists(target_path)
        target_dir = os.path.dirname(target_path)

        try:
            # --- Dry Run Logic ---
            if dry_run:
                if target_exists:
                    if on_collision == "skip":
                        logger.info(
                            f"Dry run: Target exists, would skip {operation_type} "
                            f"{source_path} to {target_path}"
                        )
                        return True  # Skipping is considered success in dry run
                    elif on_collision == "fail":
                        logger.info(
                            f"Dry run: Target exists, would fail {operation_type} "
                            f"{source_path} to {target_path}"
                        )
                        return False  # Failing is considered failure
                    elif on_collision == "overwrite":
                        logger.info(
                            f"Dry run: Target exists, would overwrite {target_path} "
                            f"before {operation_type} from {source_path}"
                        )
                        # Continue dry run logic below
                    else:  # Unknown mode, default to skip
                        logger.warning(
                            f"Dry run: Unknown on_collision mode '{on_collision}', "
                            f"defaulting to skip"
                        )
                        logger.info(
                            f"Dry run: Target exists, would skip {operation_type} "
                            f"{source_path} to {target_path}"
                        )
                        return True
                # If target doesn't exist or we are overwriting in dry run
                if not os.path.exists(target_dir):
                    logger.info(f"Dry run: Would create directory: {target_dir}")
                logger.info(f"Dry run: Would {operation_type} {source_path} to {target_path}")
                return True

            # --- Actual Operation Logic ---
            # Handle collision first
            if target_exists:
                if on_collision == "skip":
                    logger.info(f"Target exists, skipping {operation_type} for {source_path}")
                    return True  # Skipping is a successful outcome for this file
                elif on_collision == "fail":
                    logger.error(
                        f"Target exists, failing {operation_type} "
                        f"for {source_path} as per on_collision='fail'"
                    )
                    return False
                elif on_collision == "overwrite":
                    logger.info(f"Target exists, attempting to overwrite: {target_path}")
                    try:
                        # Attempt removal first - crucial change here
                        if os.path.isfile(target_path) or os.path.islink(target_path):
                            os.remove(target_path)
                        elif os.path.isdir(target_path):
                            # Decide if removing directories is allowed - safer not to by default
                            # For now, let's prevent overwriting directories implicitly
                            logger.error(
                                f"Target is a directory, cannot overwrite with file: {target_path}"
                            )
                            return False
                        logger.debug(f"Successfully removed existing target: {target_path}")
                    except OSError as e:
                        logger.error(f"Failed to remove existing target {target_path}: {e}")
                        return False  # Fail the operation if removal fails
                else:
                    logger.warning(
                        f"Unknown on_collision mode '{on_collision}', defaulting to skip"
                    )
                    logger.info(f"Target exists, skipping {operation_type} for {source_path}")
                    return True

            # If target doesn't exist, or it existed and overwrite was successful
            # Create target directory if it doesn't exist
            os.makedirs(target_dir, exist_ok=True)

            # Perform the actual file operation
            if operation_type == "move":
                logger.info(f"Moving {source_path} to {target_path}")
                shutil.move(source_path, target_path)
            elif operation_type == "symlink":
                # Ensure source exists before creating symlink
                if not os.path.exists(source_path):
                    logger.error(f"Source path for symlink does not exist: {source_path}")
                    return False
                logger.info(f"Creating symlink from {source_path} to {target_path}")
                os.symlink(os.path.abspath(source_path), target_path)
            else:  # copy (default)
                logger.info(f"Copying {source_path} to {target_path}")
                shutil.copy2(source_path, target_path)

            return True

        except Exception as e:  # Catch potential errors during makedirs or file operations
            logger.error(
                f"Error performing {operation_type} operation from {source_path} to "
                f"{target_path}: {e}"
            )
            return False

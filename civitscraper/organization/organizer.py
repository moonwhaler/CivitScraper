"""
File organizer for CivitScraper.

This module handles organizing model files based on metadata.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .config import OrganizationConfig
from .operations import FileOperationHandler
from .path_formatter import PathFormatter

logger = logging.getLogger(__name__)


class FileOrganizer:
    """
    Organizer for model files.

    This class coordinates the organization of model files based on metadata.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize file organizer.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.org_config = OrganizationConfig.from_dict(config)
        self.path_formatter = PathFormatter()
        self.file_handler = FileOperationHandler(config)
        self.dry_run = config.get("dry_run", False)

    def get_target_path(self, file_path: str, metadata: Dict[str, Any]) -> Optional[str]:
        """
        Calculate target path for a file without performing operations.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            Target path or None if calculation failed
        """
        try:
            # Get template
            template = self.path_formatter.get_template(
                self.org_config.template, self.org_config.custom_template
            )

            # Get output directory
            output_dir = self.org_config.output_dir
            if not output_dir:
                # Use default output directory
                output_dir = "{model_dir}/organized"
                logger.debug(
                    f"Using default output directory '{output_dir}' because none was specified"
                )

            # Replace {model_dir} with model directory
            output_dir = output_dir.replace("{model_dir}", os.path.dirname(file_path))

            # Format path using metadata
            relative_path = self.path_formatter.format_path(template, metadata)

            # Create target path
            target_dir = os.path.join(output_dir, relative_path)
            target_path = os.path.join(target_dir, os.path.basename(file_path))

            return target_path

        except Exception as e:
            logger.error(f"Error calculating target path for {file_path}: {e}")
            return None

    def should_process_file(self, file_path: str) -> bool:
        """
        Determine if a file should be processed based on existence.

        Args:
            file_path: Path to file

        Returns:
            True if file exists and should be processed, False otherwise
        """
        return os.path.exists(file_path)

    def organize_file(self, file_path: str, metadata: Dict[str, Any]) -> Optional[str]:
        """
        Organize a model file.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            Path to organized file or None if organization failed
        """
        # Check if organization is enabled
        if not self.org_config.enabled:
            logger.debug("Organization is disabled")
            return None

        try:
            # Get target path
            target_path = self.get_target_path(file_path, metadata)
            if not target_path:
                return None

            # Check if target path exists - we will just warn but not handle collision
            if os.path.exists(target_path):
                logger.warning(
                    f"Target path already exists: {target_path}. It will be overwritten if needed."
                )

            # Only process pre-existing files
            if self.should_process_file(file_path):
                # Perform file operation
                success = self.file_handler.perform_operation(
                    file_path, target_path, self.org_config.operation_mode, self.dry_run
                )
                if not success:
                    return None

                # Process related files that exist
                related_files = self.file_handler.get_related_files(file_path)
                for related_path, file_type in related_files:
                    if self.should_process_file(related_path):
                        # Create target path for related file
                        related_target_path = (
                            os.path.splitext(target_path)[0]
                            + os.path.splitext(related_path)[0].replace(
                                os.path.splitext(file_path)[0], ""
                            )
                            + os.path.splitext(related_path)[1]
                        )

                        # Perform operation for related file
                        self.file_handler.perform_operation(
                            related_path,
                            related_target_path,
                            self.org_config.operation_mode,
                            self.dry_run,
                        )

            return target_path

        except Exception as e:
            logger.error(f"Error organizing {file_path}: {e}")
            return None

    def get_target_paths(
        self,
        file_paths: List[str],
        metadata_dict: Dict[str, Dict[str, Any]],
    ) -> Dict[str, str]:
        """
        Get target paths for files without performing operations.

        Args:
            file_paths: List of file paths
            metadata_dict: Dictionary of file path -> metadata

        Returns:
            Dictionary mapping source paths to target paths
        """
        # Check if organization is enabled
        if not self.org_config.enabled:
            logger.debug("Organization is disabled")
            return {}

        # Calculate target paths
        target_paths = {}

        for file_path in file_paths:
            # Get metadata
            metadata = metadata_dict.get(file_path)
            if not metadata:
                logger.warning(f"No metadata found for {file_path}")
                continue

            # Get target path
            target_path = self.get_target_path(file_path, metadata)
            if target_path:
                target_paths[file_path] = target_path

        return target_paths

    def organize_files(
        self,
        file_paths: List[str],
        metadata_dict: Dict[str, Dict[str, Any]],
    ) -> List[Tuple[str, Optional[str]]]:
        """
        Organize multiple model files.

        Args:
            file_paths: List of file paths
            metadata_dict: Dictionary of file path -> metadata

        Returns:
            List of (file_path, target_path) tuples
        """
        # Check if organization is enabled
        if not self.org_config.enabled:
            logger.debug("Organization is disabled")
            return [(file_path, None) for file_path in file_paths]

        # Organize files
        results: List[Tuple[str, Optional[str]]] = []

        for file_path in file_paths:
            # Get metadata
            metadata = metadata_dict.get(file_path)
            if not metadata:
                logger.warning(f"No metadata found for {file_path}")
                results.append((file_path, None))
                continue

            # Organize file
            target_path = self.organize_file(file_path, metadata)

            # Add to results
            results.append((file_path, target_path))

        return results

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

    def organize_file(
        self, file_path: str, metadata: Dict[str, Any], force_organize: bool = False
    ) -> Optional[str]:
        """
        Organize a model file.

        Args:
            file_path: Path to model file
            metadata: Model metadata
            force_organize: If True, organize even if disabled in config

        Returns:
            Path to organized file or None if organization failed
        """
        # Check if organization is enabled (either in config or forced)
        if not (self.org_config.enabled or force_organize):
            logger.debug("Organization is disabled")
            return None

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
                logger.info(
                    f"Using default output directory '{output_dir}' because none was specified"
                )

            # Replace {model_dir} with model directory
            output_dir = output_dir.replace("{model_dir}", os.path.dirname(file_path))

            # Format path using metadata
            relative_path = self.path_formatter.format_path(template, metadata)

            # Create target path
            target_dir = os.path.join(output_dir, relative_path)
            target_path = os.path.join(target_dir, os.path.basename(file_path))

            # Check if target path exists
            if os.path.exists(target_path):
                logger.warning(f"Target path already exists: {target_path}")

                # Handle collision
                target_path = self.path_formatter.handle_collision(target_path)

            # Determine operation type
            operation_type = self.org_config.operation_mode

            # Perform file operation
            success = self.file_handler.perform_operation(
                file_path, target_path, operation_type, self.org_config.dry_run
            )

            if not success:
                return None

            # Organize related files
            related_files = self.file_handler.get_related_files(file_path)

            for related_path, file_type in related_files:
                # Create target path for related file
                related_target_path = (
                    os.path.splitext(target_path)[0]
                    + os.path.splitext(related_path)[0].replace(os.path.splitext(file_path)[0], "")
                    + os.path.splitext(related_path)[1]
                )

                # Perform operation for related file
                self.file_handler.perform_operation(
                    related_path, related_target_path, operation_type, self.org_config.dry_run
                )

            return target_path

        except Exception as e:
            logger.error(f"Error organizing {file_path}: {e}")
            return None

    def organize_files(
        self,
        file_paths: List[str],
        metadata_dict: Dict[str, Dict[str, Any]],
        force_organize: bool = False,
    ) -> List[Tuple[str, Optional[str]]]:
        """
        Organize multiple model files.

        Args:
            file_paths: List of file paths
            metadata_dict: Dictionary of file path -> metadata
            force_organize: If True, organize even if disabled in config

        Returns:
            List of (file_path, target_path) tuples
        """
        # Check if organization is enabled (either in config or forced)
        if not (self.org_config.enabled or force_organize):
            logger.debug("Organization is disabled")
            return [(file_path, None) for file_path in file_paths]

        # Organize files
        results = []

        for file_path in file_paths:
            # Get metadata
            metadata = metadata_dict.get(file_path)
            if not metadata:
                logger.warning(f"No metadata found for {file_path}")
                results.append((file_path, None))
                continue

            # Organize file
            target_path = self.organize_file(file_path, metadata, force_organize)

            # Add to results
            results.append((file_path, target_path))

        return results

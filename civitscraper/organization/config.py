"""
Configuration for file organization.

This module contains configuration classes for the file organization feature.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class OrganizationConfig:
    """Configuration for file organization."""

    enabled: bool = False
    template: Optional[str] = None
    custom_template: Optional[str] = None
    output_dir: Optional[str] = None
    operation_mode: str = "copy"
    on_collision: str = "skip"  # Options: 'skip', 'overwrite', 'fail'

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "OrganizationConfig":
        """
        Create an OrganizationConfig from a configuration dictionary.

        Args:
            config: Configuration dictionary

        Returns:
            OrganizationConfig instance
        """
        org_config = config.get("organization", {})
        defaults = config.get("defaults", {}).get("organization", {})

        # Get enabled flag
        enabled = org_config.get("enabled", False)

        # Get template and custom template
        template = org_config.get("template")
        custom_template = org_config.get("custom_template")

        # Get output directory
        output_dir = org_config.get("output_dir")

        # Get operation mode
        # First check if it's in the organization config
        operation_mode = org_config.get("operation_mode")

        # If not, check if it's in the defaults.organization section
        if operation_mode is None and defaults:
            operation_mode = defaults.get("operation_mode", "copy")
        else:
            # Default to copy if not found
            operation_mode = operation_mode or "copy"

        # Fallback to legacy configuration if present
        if operation_mode == "copy":  # Only check legacy if modern isn't set to move/symlink
            if "move_files" in org_config and org_config.get("move_files", False):
                operation_mode = "move"
                logger.warning(
                    "Using legacy 'move_files: true'. Please use 'operation_mode: move' instead."
                )
            elif "create_symlinks" in org_config and org_config.get("create_symlinks", False):
                operation_mode = "symlink"
                logger.warning(
                    "Using legacy 'create_symlinks: true'. "
                    + "Please use 'operation_mode: symlink' instead."
                )

        # Get collision handling mode
        on_collision = org_config.get("on_collision")
        if on_collision is None and defaults:
            on_collision = defaults.get("on_collision", "skip")
        else:
            on_collision = on_collision or "skip"

        # Validate on_collision
        valid_collision_modes = ["skip", "overwrite", "fail"]
        if on_collision not in valid_collision_modes:
            logger.warning(
                f"Invalid on_collision mode '{on_collision}'. "
                f"Defaulting to 'skip'. Valid modes are: {valid_collision_modes}"
            )
            on_collision = "skip"

        return cls(
            enabled=enabled,
            template=template,
            custom_template=custom_template,
            output_dir=output_dir,
            operation_mode=operation_mode,
            on_collision=on_collision,
        )

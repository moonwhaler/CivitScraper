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
        if "move_files" in org_config and org_config.get("move_files", False):
            operation_mode = "move"
        elif "create_symlinks" in org_config and org_config.get("create_symlinks", False):
            operation_mode = "symlink"

        return cls(
            enabled=enabled,
            template=template,
            custom_template=custom_template,
            output_dir=output_dir,
            operation_mode=operation_mode,
        )

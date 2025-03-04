"""
Path formatter for file organization.

This module handles formatting file paths based on metadata.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PathFormatter:
    """Formatter for file paths based on metadata."""

    def __init__(self):
        """Initialize path formatter."""
        # Predefined templates
        self.templates = {
            "by_type": "{type}",
            "by_creator": "{creator}",
            "by_type_and_creator": "{type}/{creator}",
            "by_type_and_basemodel": "{type}/{base_model}",
            "by_base_model": "{base_model}/{type}",
            "by_nsfw": "{nsfw}/{type}",
            "by_type_basemodel_nsfw": "{type}/{base_model}/{nsfw}",
            "by_date": "{year}/{month}/{type}",
            "by_model_info": "{model_type}/{model_name}",
        }

    def get_template(self, template_name: Optional[str], custom_template: Optional[str]) -> str:
        """
        Get the template to use for path formatting.

        Args:
            template_name: Name of predefined template
            custom_template: Custom template string

        Returns:
            Template string
        """
        if custom_template:
            logger.debug(f"Using custom template: {custom_template}")
            return custom_template
        elif template_name and template_name in self.templates:
            template = self.templates[template_name]
            logger.debug(f"Using predefined template '{template_name}': {template}")
            return template
        else:
            # Use default template
            template = self.templates["by_type"]
            logger.info(
                f"Using default template 'by_type' because template '{template_name}' "
                "was not specified or not found"
            )
            return template

    def format_path(self, template: str, metadata: Dict[str, Any]) -> str:
        """
        Format path using metadata.

        Args:
            template: Path template
            metadata: Model metadata

        Returns:
            Formatted path
        """
        # Get model information
        model_info = metadata.get("model", {})

        # Get model name
        model_name = metadata.get("name", "Unknown")

        # Get model type
        model_type = model_info.get("type", "Unknown")

        # Get model creator
        creator = model_info.get("creator", {}).get("username", "Unknown")

        # Get base model
        base_model = metadata.get("baseModel", "Unknown")

        # Get NSFW status
        nsfw = "nsfw" if model_info.get("nsfw", False) else "sfw"

        # Get creation date
        created_at = metadata.get("createdAt", "")
        year = created_at[:4] if created_at else "Unknown"
        month = created_at[5:7] if created_at else "Unknown"

        # Format path
        path = template
        path = path.replace("{model_name}", self.sanitize_path(model_name))
        path = path.replace("{model_type}", self.sanitize_path(model_type))
        path = path.replace("{type}", self.sanitize_path(model_type))
        path = path.replace("{creator}", self.sanitize_path(creator))
        path = path.replace("{base_model}", self.sanitize_path(base_model))
        path = path.replace("{nsfw}", nsfw)
        path = path.replace("{year}", year)
        path = path.replace("{month}", month)

        return path

    def sanitize_path(self, path: str) -> str:
        """
        Sanitize path by replacing invalid characters.

        Args:
            path: Path to sanitize

        Returns:
            Sanitized path
        """
        # Replace invalid characters
        invalid_chars = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
        for char in invalid_chars:
            path = path.replace(char, "_")

        # Remove leading and trailing dots and spaces
        path = path.strip(". ")

        return path

    # Collision detection removed - files should be overwritten or skipped based on skip_existing

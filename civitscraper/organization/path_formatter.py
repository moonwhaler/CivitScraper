"""
Path formatter for file organization.

This module handles formatting file paths based on metadata.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def round_to_half(value: float) -> str:
    """Round a value to nearest 0.5 and format with one decimal."""
    rounded = round(value * 2) / 2
    rounded = min(max(rounded, 1.0), 5.0)  # Ensure between 1-5
    return f"{rounded: .1f}"


def calculate_weighted_rating(rating: float, rating_count: int, download_count: int) -> str:
    """Calculate weighted rating (1-5) with confidence adjustment."""
    if rating_count == 0:
        return "1.0"

    rating_ratio = rating_count / max(download_count, 1)
    confidence = min(rating_ratio * 5, 1.0)

    weighted = 3.0 + (rating - 3.0) * confidence
    weighted = min(max(weighted, 1.0), 5.0)
    weighted = round(weighted * 2) / 2
    return f"{weighted: .1f}"


def calculate_weighted_thumbsup(download_count: int, thumbs_up_count: int) -> str:
    """Calculate weighted thumbs up rating (1-5) using 5% steps."""
    if download_count == 0:
        return "1.0"

    ratio = thumbs_up_count / download_count
    weighted = 1.0 + min(ratio * 5, 1.0) * 4.0

    # Round to nearest 0.5
    weighted = round(weighted * 2) / 2
    return f"{weighted: .1f}"


class PathFormatter:
    """Formatter for file paths based on metadata."""

    def __init__(self):
        """Initialize path formatter."""
        # Predefined templates
        self.templates = {
            "by_rating": "{weighted_rating}/{type}",
            "by_type_and_rating": "{type}/{weighted_rating}",
            "by_raw_rating": "{rating}/{type}",
            "by_type_and_raw_rating": "{type}/{rating}",
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
        model_info = metadata.get("model", {})
        model_name = metadata.get("name", "Unknown")
        model_type = model_info.get("type", "Unknown")

        creator = model_info.get("creator", {}).get("username", "Unknown")
        base_model = metadata.get("baseModel", "Unknown")
        nsfw = "nsfw" if model_info.get("nsfw", False) else "sfw"

        created_at = metadata.get("createdAt", "")
        year = created_at[:4] if created_at else "Unknown"
        month = created_at[5:7] if created_at else "Unknown"

        stats = metadata.get("stats", {})

        rating = stats.get("rating", 0.0)
        rating_count = stats.get("ratingCount", 0)
        download_count = stats.get("downloadCount", 0)
        thumbs_up_count = stats.get("thumbsUpCount", 0)

        rounded_rating = round_to_half(rating)
        weighted_rating = calculate_weighted_rating(rating, rating_count, download_count)
        weighted_thumbsup = calculate_weighted_thumbsup(download_count, thumbs_up_count)

        path = template
        path = path.replace("{rating}", f"rating_{rounded_rating}")
        path = path.replace("{weighted_rating}", f"rating_{weighted_rating}")
        path = path.replace("{weighted_thumbsup}", f"thumbs_{weighted_thumbsup}")
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
        invalid_chars = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
        for char in invalid_chars:
            path = path.replace(char, "_")

        path = path.strip(". ")

        return path

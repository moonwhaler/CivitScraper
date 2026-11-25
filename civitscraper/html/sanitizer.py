"""
Data sanitization utilities for HTML generation.

This module handles sanitizing and encoding data for HTML generation.
"""

import base64
import html as html_lib
import json
import logging
import re
from typing import Any, Dict, List, Optional

import nh3

logger = logging.getLogger(__name__)


class DataSanitizer:
    """Sanitizer for data used in HTML generation."""

    def sanitize_json_data(self, data: List[Dict[str, Any]]) -> str:
        """
        Sanitize and encode image data to avoid JSON parsing issues.

        Args:
            data: List of image data dictionaries

        Returns:
            Base64 encoded JSON string
        """
        try:
            # First, sanitize any problematic strings in the data
            sanitized_data = []
            for item in data:
                sanitized_item = {}
                for key, value in item.items():
                    if isinstance(value, str):
                        # Fix common escaping issues in strings
                        # Replace double-escaped parentheses with single-escaped
                        value = self.sanitize_string(value)
                    sanitized_item[key] = value
                sanitized_data.append(sanitized_item)

            json_str = json.dumps(sanitized_data, ensure_ascii=False)

            # Encode as base64 to avoid any escaping issues
            encoded = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

            logger.debug(f"Successfully encoded data (length: {len(json_str)})")
            return encoded
        except Exception as e:
            logger.error(f"Error encoding data: {e}")
            return base64.b64encode("[]".encode("utf-8")).decode("utf-8")  # Fallback

    def sanitize_string(self, value: str) -> str:
        """
        Sanitize string values to avoid JSON parsing issues.

        Args:
            value: String to sanitize

        Returns:
            Sanitized string
        """
        # Replace double-escaped parentheses with single-escaped
        value = re.sub(r"\\\\([()])", r"\\\1", value)

        # TODO: Add more sanitization rules if other issues arise

        return value


# Markup CivitAI model descriptions actually use (rich-text editor output).
_DESCRIPTION_TAGS = {
    "p",
    "br",
    "hr",
    "span",
    "div",
    "a",
    "b",
    "i",
    "u",
    "s",
    "del",
    "strong",
    "em",
    "sub",
    "sup",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "code",
    "pre",
    "blockquote",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}
_DESCRIPTION_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
}


def sanitize_description(html: Optional[str]) -> str:
    """
    Sanitize a model description (creator-supplied HTML) for safe rendering.

    Scripts, event handlers, styles and non-http(s) URLs (``javascript:``,
    ``data:``) are removed; links get ``rel="noopener noreferrer"``.

    Args:
        html: Raw description HTML from the CivitAI API

    Returns:
        Sanitized HTML ("" for empty input)
    """
    if not html:
        return ""
    return str(
        nh3.clean(
            str(html),
            tags=_DESCRIPTION_TAGS,
            attributes=_DESCRIPTION_ATTRIBUTES,
            url_schemes={"http", "https"},
            link_rel="noopener noreferrer",
        )
    )


def description_excerpt(html: Optional[str], limit: int = 300) -> str:
    """
    Plain-text excerpt of a description for gallery search.

    Tags are stripped, entities decoded and whitespace collapsed; the text is cut
    at a word boundary at most ``limit`` characters long.

    Args:
        html: Raw description HTML
        limit: Maximum excerpt length

    Returns:
        Plain-text excerpt ("" for empty input)
    """
    if not html:
        return ""
    text = nh3.clean(str(html), tags=set())
    text = re.sub(r"\s+", " ", html_lib.unescape(text)).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip()

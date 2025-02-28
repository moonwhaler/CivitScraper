"""
Data sanitization utilities for HTML generation.

This module handles sanitizing and encoding data for HTML generation.
"""

import base64
import json
import logging
import re
from typing import Any, Dict, List

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

            # Convert to JSON string
            json_str = json.dumps(sanitized_data, ensure_ascii=False)

            # Encode as base64 to avoid any escaping issues
            encoded = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

            logger.debug(f"Successfully encoded data (length: {len(json_str)})")
            return encoded
        except Exception as e:
            logger.error(f"Error encoding data: {e}")
            # Return empty array as fallback
            return base64.b64encode("[]".encode("utf-8")).decode("utf-8")

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

        # Add more sanitization rules as needed

        return value

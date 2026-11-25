"""
Response parsing for the CivitAI API client.

This module turns API response bodies into dictionaries.
"""

import json
import logging
from typing import Any, Dict

from .exceptions import ParseError

logger = logging.getLogger(__name__)


def parse_json(response_text: str) -> Dict[str, Any]:
    """
    Parse a JSON response body.

    Args:
        response_text: Response text

    Returns:
        Parsed JSON

    Raises:
        ParseError: If parsing fails
    """
    try:
        result: Dict[str, Any] = json.loads(response_text)
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        raise ParseError(str(e))

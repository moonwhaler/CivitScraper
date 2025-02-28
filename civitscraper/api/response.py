"""
Response parser for CivitAI API client.

This module handles parsing API responses into model objects.
"""

import json
import logging
from typing import Any, Dict, Type, TypeVar

from .exceptions import ParseError
from .models import ImageSearchResult, Model, ModelVersion, SearchResult

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ResponseParser:
    """Parser for CivitAI API responses."""

    def __init__(self):
        """Initialize response parser."""
        logger.debug("Initialized response parser")

    def parse_json(self, response_text: str) -> Dict[str, Any]:
        """
        Parse JSON response.

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

    def parse_model(self, data: Dict[str, Any]) -> Model:
        """
        Parse model data.

        Args:
            data: Model data

        Returns:
            Model object

        Raises:
            ParseError: If parsing fails
        """
        try:
            return Model.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse model data: {e}")
            raise ParseError(f"Failed to parse model data: {e}")

    def parse_model_version(self, data: Dict[str, Any]) -> ModelVersion:
        """
        Parse model version data.

        Args:
            data: Model version data

        Returns:
            ModelVersion object

        Raises:
            ParseError: If parsing fails
        """
        try:
            return ModelVersion.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse model version data: {e}")
            raise ParseError(f"Failed to parse model version data: {e}")

    def parse_search_result(self, data: Dict[str, Any]) -> SearchResult:
        """
        Parse search result data.

        Args:
            data: Search result data

        Returns:
            SearchResult object

        Raises:
            ParseError: If parsing fails
        """
        try:
            return SearchResult.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse search result data: {e}")
            raise ParseError(f"Failed to parse search result data: {e}")

    def parse_image_search_result(self, data: Dict[str, Any]) -> ImageSearchResult:
        """
        Parse image search result data.

        Args:
            data: Image search result data

        Returns:
            ImageSearchResult object

        Raises:
            ParseError: If parsing fails
        """
        try:
            return ImageSearchResult.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse image search result data: {e}")
            raise ParseError(f"Failed to parse image search result data: {e}")

    def parse_response(self, response_text: str, response_type: Type[T]) -> T:
        """
        Parse response into specified type.

        Args:
            response_text: Response text
            response_type: Type to parse into

        Returns:
            Parsed response

        Raises:
            ParseError: If parsing fails
        """
        # Parse JSON
        data = self.parse_json(response_text)

        # Parse into specified type
        if response_type == Model:
            return self.parse_model(data)  # type: ignore
        elif response_type == ModelVersion:
            return self.parse_model_version(data)  # type: ignore
        elif response_type == SearchResult:
            return self.parse_search_result(data)  # type: ignore
        elif response_type == ImageSearchResult:
            return self.parse_image_search_result(data)  # type: ignore
        else:
            logger.error(f"Unsupported response type: {response_type}")
            raise ParseError(f"Unsupported response type: {response_type}")

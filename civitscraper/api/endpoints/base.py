"""Base endpoint class for CivitAI API.

This module provides the base endpoint class that all endpoint-specific classes inherit from.
"""

from typing import Any, Dict, Optional, Type, TypeVar

T = TypeVar("T")


class BaseEndpoint:
    """Base class for API endpoints."""

    def __init__(self, client: Any):
        """
        Initialize endpoint.

        Args:
            client: Base client instance
        """
        self.client = client

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
        response_type: Optional[Type[T]] = None,
    ) -> Any:
        """
        Make API request.

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request data
            force_refresh: Force refresh cache
            response_type: Type to parse response into

        Returns:
            API response
        """
        return self.client._make_request(
            method=method,
            endpoint=endpoint,
            params=params,
            data=data,
            force_refresh=force_refresh,
            response_type=response_type,
        )

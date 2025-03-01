"""Images endpoint for CivitAI API.

This module handles all image-related API operations.
"""

from typing import Any, Dict, Optional, Tuple

from ..models import ImageSearchResult
from .base import BaseEndpoint


class ImagesEndpoint(BaseEndpoint):
    """Endpoint for image operations."""

    def get(
        self,
        model_id: Optional[int] = None,
        model_version_id: Optional[int] = None,
        limit: int = 100,
        page: int = 1,
        force_refresh: bool = False,
        response_type: Optional[type] = None,
    ) -> Any:
        """
        Get images.

        Args:
            model_id: Filter by model ID
            model_version_id: Filter by model version ID
            limit: Results per page
            page: Page number
            force_refresh: Force refresh cache
            response_type: Type to parse response into (ImageSearchResult or None for dict)

        Returns:
            Images data as dict or ImageSearchResult object
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "page": page,
        }

        if model_id:
            params["modelId"] = model_id

        if model_version_id:
            params["modelVersionId"] = model_version_id

        return self._make_request(
            "GET",
            "images",
            params=params,
            force_refresh=force_refresh,
            response_type=response_type,
        )

    def download(self, url: str, output_path: str) -> bool:
        """
        Download image from URL.

        Args:
            url: Image URL
            output_path: Output file path

        Returns:
            True if download was successful, False otherwise
        """
        return self.client.download(url, output_path)

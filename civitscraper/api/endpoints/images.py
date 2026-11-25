"""Images endpoint for CivitAI API.

This module handles image-related API operations.
"""

from typing import Any, Dict, Optional

from .base import BaseEndpoint


class ImagesEndpoint(BaseEndpoint):
    """Endpoint for image operations."""

    def get(
        self,
        model_id: Optional[int] = None,
        model_version_id: Optional[int] = None,
        limit: int = 100,
        page: int = 1,
        nsfw: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Get images.

        Args:
            model_id: Filter by model ID
            model_version_id: Filter by model version ID
            limit: Results per page
            page: Page number
            nsfw: Browsing-level enum (None/Soft/Mature/X) to include NSFW images
            force_refresh: Force refresh cache

        Returns:
            Images data
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "page": page,
        }

        if model_id:
            params["modelId"] = model_id

        if model_version_id:
            params["modelVersionId"] = model_version_id

        if nsfw is not None:
            params["nsfw"] = nsfw

        return self._make_request("GET", "images", params=params, force_refresh=force_refresh)

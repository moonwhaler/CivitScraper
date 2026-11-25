"""Model versions endpoint for CivitAI API.

This module handles model version-related API operations.
"""

from typing import Any, Dict

from .base import BaseEndpoint


class VersionsEndpoint(BaseEndpoint):
    """Endpoint for model version operations."""

    def get_by_hash(self, hash_value: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get model version by file hash.

        Args:
            hash_value: Model file hash
            force_refresh: Force refresh cache

        Returns:
            Model version data
        """
        return self._make_request(
            "GET", f"model-versions/by-hash/{hash_value}", force_refresh=force_refresh
        )

    def get(self, version_id: int, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get a model version by ID (same shape as the by-hash lookup).

        Args:
            version_id: Model version ID
            force_refresh: Force refresh cache

        Returns:
            Model version data
        """
        return self._make_request(
            "GET", f"model-versions/{version_id}", force_refresh=force_refresh
        )

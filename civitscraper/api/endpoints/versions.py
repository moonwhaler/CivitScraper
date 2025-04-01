"""Model versions endpoint for CivitAI API.

This module handles all model version-related API operations.
"""

from typing import Any, Dict, Optional, Union

from ..models import ModelVersion
from .base import BaseEndpoint


class VersionsEndpoint(BaseEndpoint):
    """Endpoint for model version operations."""

    def get(
        self, version_id: int, force_refresh: bool = False, response_type: Optional[type] = None
    ) -> Union[Dict[str, Any], ModelVersion]:
        """
        Get model version by ID.

        Args:
            version_id: Model version ID
            force_refresh: Force refresh cache
            response_type: Type to parse response into (ModelVersion or None for dict)

        Returns:
            Model version data as dict or ModelVersion object
        """
        return self._make_request(
            "GET",
            f"model-versions/{version_id}",
            force_refresh=force_refresh,
            response_type=response_type,
        )

    def get_by_hash(
        self, hash_value: str, force_refresh: bool = False, response_type: Optional[type] = None
    ) -> Union[Dict[str, Any], ModelVersion]:
        """
        Get model version by hash.

        Args:
            hash_value: Model hash
            force_refresh: Force refresh cache
            response_type: Type to parse response into (ModelVersion or None for dict)

        Returns:
            Model version data as dict or ModelVersion object
        """
        return self._make_request(
            "GET",
            f"model-versions/by-hash/{hash_value}",
            force_refresh=force_refresh,
            response_type=response_type,
        )

    def download(self, version_id: int, output_path: str) -> bool:
        """
        Download model file.

        Args:
            version_id: Model version ID
            output_path: Output file path

        Returns:
            True if download was successful, False otherwise
        """
        try:
            version_data = self.get(version_id)

            if isinstance(version_data, dict):
                download_url = version_data.get("downloadUrl")
            else:
                download_url = version_data.download_url

            if not download_url:
                return False

            result = self.client.download(download_url, output_path)
            return bool(result)

        except Exception:
            return False

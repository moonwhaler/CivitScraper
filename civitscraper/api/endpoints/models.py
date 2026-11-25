"""Models endpoint for CivitAI API.

This module handles model-related API operations.
"""

from typing import Any, Dict

from .base import BaseEndpoint


class ModelsEndpoint(BaseEndpoint):
    """Endpoint for model operations."""

    def get(self, model_id: int, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get model by ID.

        Args:
            model_id: Model ID
            force_refresh: Force refresh cache

        Returns:
            Model data
        """
        return self._make_request("GET", f"models/{model_id}", force_refresh=force_refresh)

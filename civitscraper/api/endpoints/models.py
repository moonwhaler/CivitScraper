"""Models endpoint for CivitAI API.

This module handles all model-related API operations.
"""

from typing import Any, Dict, List, Optional, Union, cast

from ..models import Model, SearchResult
from .base import BaseEndpoint


class ModelsEndpoint(BaseEndpoint):
    """Endpoint for model operations."""

    def get(
        self, model_id: int, force_refresh: bool = False, response_type: Optional[type] = None
    ) -> Union[Dict[str, Any], Model]:
        """
        Get model by ID.

        Args:
            model_id: Model ID
            force_refresh: Force refresh cache
            response_type: Type to parse response into (Model or None for dict)

        Returns:
            Model data as dict or Model object
        """
        return self._make_request(
            "GET",
            f"models/{model_id}",
            force_refresh=force_refresh,
            response_type=response_type,
        )

    def get_by_hash(
        self, hash_value: str, force_refresh: bool = False, response_type: Optional[type] = None
    ) -> Optional[Union[Dict[str, Any], Model]]:
        """
        Get model by hash.

        Args:
            hash_value: Model hash
            force_refresh: Force refresh cache
            response_type: Type to parse response into (Model or None for dict)

        Returns:
            Model data as dict or Model object, or None if not found
        """
        params: Dict[str, Any] = {"hashes[]": hash_value}

        response = self._make_request(
            "GET",
            "models",
            params=params,
            force_refresh=force_refresh,
            response_type=response_type,
        )

        # Extract first item from response
        if isinstance(response, SearchResult) and response.items:
            return cast(Model, response.items[0])
        if isinstance(response, dict):
            items = response.get("items", [])
            if items:
                return cast(Dict[str, Any], items[0])
        return None

    def search(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        username: Optional[str] = None,
        types: Optional[List[str]] = None,
        sort: Optional[str] = None,
        period: Optional[str] = None,
        nsfw: Optional[bool] = None,
        limit: int = 100,
        page: int = 1,
        force_refresh: bool = False,
        response_type: Optional[type] = None,
    ) -> Union[Dict[str, Any], SearchResult]:
        """
        Search models.

        Args:
            query: Search query
            tags: Tags to filter by
            username: Username to filter by
            types: Model types to filter by
            sort: Sort order
            period: Time period
            nsfw: Filter by NSFW status
            limit: Results per page
            page: Page number
            force_refresh: Force refresh cache
            response_type: Type to parse response into (SearchResult or None for dict)

        Returns:
            Search results as dict or SearchResult object
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "page": page,
        }

        if query:
            params["query"] = query

        if tags:
            params["tag"] = ",".join(tags)

        if username:
            params["username"] = username

        if types:
            params["types"] = ",".join(types)

        if sort:
            params["sort"] = sort

        if period:
            params["period"] = period

        if nsfw is not None:
            params["nsfw"] = str(nsfw).lower()

        return self._make_request(
            "GET",
            "models",
            params=params,
            force_refresh=force_refresh,
            response_type=response_type,
        )

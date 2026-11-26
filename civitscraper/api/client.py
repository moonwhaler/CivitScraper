"""CivitAI API client."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from .base_client import BaseClient
from .endpoints import ImagesEndpoint, ModelsEndpoint, VersionsEndpoint
from .exceptions import ClientError

logger = logging.getLogger(__name__)


class CivitAIClient:
    """CivitAI API client for interacting with models, versions and images."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize client with configuration."""
        self._base_client = BaseClient(config)
        self._models = ModelsEndpoint(self._base_client)
        self._versions = VersionsEndpoint(self._base_client)
        self._images = ImagesEndpoint(self._base_client)
        logger.debug("Initialized CivitAI API client")

    @property
    def api_key(self) -> Optional[str]:
        """Get API key."""
        return self._base_client.api_key

    @property
    def download_rate_limiter(self) -> Any:
        """Rate limiter shared by file downloads."""
        return self._base_client.download_rate_limiter

    @property
    def base_url(self) -> Any:
        """Get base URL."""
        return self._base_client.base_url

    @property
    def timeout(self) -> Any:
        """Get timeout."""
        return self._base_client.timeout

    @property
    def max_retries(self) -> Any:
        """Get max retries."""
        return self._base_client.max_retries

    @property
    def user_agent(self) -> Any:
        """Get user agent."""
        return self._base_client.user_agent

    def get_model(self, model_id: int, force_refresh: bool = False) -> Dict[str, Any]:
        """Get model by ID."""
        return self._models.get(model_id, force_refresh=force_refresh)

    def get_model_version_by_hash(
        self, hash_value: str, force_refresh: bool = False
    ) -> Dict[str, Any]:
        """Get model version by file hash."""
        return self._versions.get_by_hash(hash_value, force_refresh=force_refresh)

    def get_model_version(self, version_id: int, force_refresh: bool = False) -> Dict[str, Any]:
        """Get model version by ID (prompts included, like the by-hash lookup)."""
        return self._versions.get(version_id, force_refresh=force_refresh)

    def get_images(
        self,
        *,
        model_id: Optional[int] = None,
        model_version_id: Optional[int] = None,
        limit: int = 100,
        page: int = 1,
        nsfw: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Get images for model or version."""
        return self._images.get(
            model_id=model_id,
            model_version_id=model_version_id,
            limit=limit,
            page=page,
            nsfw=nsfw,
            force_refresh=force_refresh,
        )

    def download_image(self, url: str, output_path: str) -> Tuple[bool, Optional[str]]:
        """Download image from URL to the specified path."""
        return self._base_client.request_handler.download(
            url, output_path, dry_run=self._base_client.dry_run
        )

    def get_parent_model_with_versions(
        self, model_id: int, current_version_id: int, force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch parent model and return structured data with sibling versions.

        Args:
            model_id: Parent model ID
            current_version_id: ID of the current version (to mark as current)
            force_refresh: Force refresh cache

        Returns:
            Dictionary with parentModel and siblingVersions, or None if CivitAI
            answered 404 (the model was deleted)

        Raises:
            CivitAIError: Network errors, server errors, rate limits, an open circuit
                breaker; ValueError for a response without model data. These are
                temporary: the caller keeps what it has and tries again next run.
        """
        try:
            model_data = self.get_model(model_id, force_refresh=force_refresh)
        except ClientError as e:
            if e.status_code == 404:
                logger.info(f"Parent model {model_id} is not on CivitAI (404)")
                return None
            raise
        if not isinstance(model_data, dict) or not model_data.get("id"):
            raise ValueError(f"No model data in the response for model {model_id}")

        sibling_versions: List[Dict[str, Any]] = []
        parent_model = {
            "id": model_data.get("id"),
            "name": model_data.get("name"),
            "type": model_data.get("type"),
            "nsfw": model_data.get("nsfw", False),
            "creator": {"username": model_data.get("creator", {}).get("username", "Unknown")},
            "tags": model_data.get("tags", []),
        }
        for version in model_data.get("modelVersions", []):
            stats = version.get("stats", {})
            version_id = version.get("id")
            sibling_versions.append(
                {
                    "id": version_id,
                    "name": version.get("name"),
                    "baseModel": version.get("baseModel"),
                    "createdAt": version.get("createdAt"),
                    "downloadCount": stats.get("downloadCount", 0),
                    "isCurrent": version_id == current_version_id,
                }
            )

        # Sort by creation date (newest first)
        sibling_versions.sort(key=lambda v: v.get("createdAt") or "", reverse=True)

        return {
            "parentModel": parent_model,
            "siblingVersions": sibling_versions,
        }

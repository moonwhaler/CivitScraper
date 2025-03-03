"""CivitAI API client with backward compatibility."""

import logging
from typing import Any, Dict, List, Optional, Tuple, TypeVar, Union

from .base_client import BaseClient
from .endpoints import ImagesEndpoint, ModelsEndpoint, VersionsEndpoint
from .models import ImageSearchResult, Model, ModelVersion, SearchResult

logger = logging.getLogger(__name__)
T = TypeVar("T")


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

    def get_model(
        self, model_id: int, force_refresh: bool = False, typed: bool = False
    ) -> Union[Dict[str, Any], Model]:
        """Get model by ID."""
        response = self._models.get(
            model_id, force_refresh=force_refresh, response_type=Model if typed else None
        )
        return response

    def get_model_typed(self, model_id: int, force_refresh: bool = False) -> Model:
        """Get model by ID with type checking."""
        result = self.get_model(model_id, force_refresh, typed=True)
        assert isinstance(result, Model)
        return result

    def get_model_by_hash(
        self, hash_value: str, force_refresh: bool = False, typed: bool = False
    ) -> Optional[Union[Dict[str, Any], Model]]:
        """Get model by hash value."""
        response = self._models.get_by_hash(
            hash_value, force_refresh=force_refresh, response_type=Model if typed else None
        )
        return response

    def get_model_by_hash_typed(
        self, hash_value: str, force_refresh: bool = False
    ) -> Optional[Model]:
        """Get model by hash value with type checking."""
        result = self.get_model_by_hash(hash_value, force_refresh, typed=True)
        if result is not None:
            assert isinstance(result, Model)
            return result
        return None

    def search_models(
        self,
        *,
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
        typed: bool = False,
    ) -> Union[Dict[str, Any], SearchResult]:
        """Search models with optional filters."""
        response = self._models.search(
            query=query,
            tags=tags,
            username=username,
            types=types,
            sort=sort,
            period=period,
            nsfw=nsfw,
            limit=limit,
            page=page,
            force_refresh=force_refresh,
            response_type=SearchResult if typed else None,
        )
        return response

    def search_models_typed(self, **kwargs) -> SearchResult:
        """Search models with type checking."""
        result = self.search_models(**kwargs, typed=True)
        assert isinstance(result, SearchResult)
        return result

    def get_model_version(
        self, version_id: int, force_refresh: bool = False, typed: bool = False
    ) -> Union[Dict[str, Any], ModelVersion]:
        """Get model version by ID."""
        response = self._versions.get(
            version_id, force_refresh=force_refresh, response_type=ModelVersion if typed else None
        )
        return response

    def get_model_version_typed(self, version_id: int, force_refresh: bool = False) -> ModelVersion:
        """Get model version by ID with type checking."""
        result = self.get_model_version(version_id, force_refresh, typed=True)
        assert isinstance(result, ModelVersion)
        return result

    def get_model_version_by_hash(
        self, hash_value: str, force_refresh: bool = False, typed: bool = False
    ) -> Union[Dict[str, Any], ModelVersion]:
        """Get model version by hash value."""
        response = self._versions.get_by_hash(
            hash_value, force_refresh=force_refresh, response_type=ModelVersion if typed else None
        )
        return response

    def get_model_version_by_hash_typed(
        self, hash_value: str, force_refresh: bool = False
    ) -> ModelVersion:
        """Get model version by hash value with type checking."""
        result = self.get_model_version_by_hash(hash_value, force_refresh, typed=True)
        assert isinstance(result, ModelVersion)
        return result

    def download_model(self, version_id: int, output_path: str) -> bool:
        """Download model file to the specified path."""
        return self._versions.download(version_id, output_path)

    def get_images(
        self,
        *,
        model_id: Optional[int] = None,
        model_version_id: Optional[int] = None,
        limit: int = 100,
        page: int = 1,
        force_refresh: bool = False,
        typed: bool = False,
    ) -> Union[Dict[str, Any], ImageSearchResult]:
        """Get images for model or version."""
        response = self._images.get(
            model_id=model_id,
            model_version_id=model_version_id,
            limit=limit,
            page=page,
            force_refresh=force_refresh,
            response_type=ImageSearchResult if typed else None,
        )
        return response

    def get_images_typed(self, **kwargs) -> ImageSearchResult:
        """Get images with type checking."""
        result = self.get_images(**kwargs, typed=True)
        assert isinstance(result, ImageSearchResult)
        return result

    def download_image(self, url: str, output_path: str) -> Tuple[bool, Optional[str]]:
        """Download image from URL to the specified path."""
        return self._base_client.request_handler.download(
            url, output_path, dry_run=self._base_client.dry_run
        )

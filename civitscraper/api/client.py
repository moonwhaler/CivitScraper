"""CivitAI API client with backward compatibility."""

import logging
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar, Union, overload

from .base_client import BaseClient
from .endpoints import ImagesEndpoint, ModelsEndpoint, VersionsEndpoint
from .models import ImageSearchResult, Model, ModelVersion, SearchResult

logger = logging.getLogger(__name__)
T = TypeVar('T')

class CivitAIClient:
    def __init__(self, config: Dict[str, Any]) -> None:
        self._base_client = BaseClient(config)
        self._models = ModelsEndpoint(self._base_client)
        self._versions = VersionsEndpoint(self._base_client)
        self._images = ImagesEndpoint(self._base_client)
        logger.debug("Initialized CivitAI API client")

    @overload
    def get_model(self, model_id: int, force_refresh: bool = False) -> Dict[str, Any]: ...
    @overload
    def get_model(self, model_id: int, force_refresh: bool = False, typed: bool = True) -> Model: ...
    def get_model(self, model_id: int, force_refresh: bool = False, typed: bool = False) -> Union[Dict[str, Any], Model]:
        return self._models.get(model_id, force_refresh=force_refresh, response_type=Model if typed else None)

    def get_model_typed(self, model_id: int, force_refresh: bool = False) -> Model:
        return self.get_model(model_id, force_refresh, typed=True)

    @overload
    def get_model_by_hash(self, hash_value: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]: ...
    @overload
    def get_model_by_hash(self, hash_value: str, force_refresh: bool = False, typed: bool = True) -> Optional[Model]: ...
    def get_model_by_hash(self, hash_value: str, force_refresh: bool = False, typed: bool = False) -> Optional[Union[Dict[str, Any], Model]]:
        return self._models.get_by_hash(hash_value, force_refresh=force_refresh, response_type=Model if typed else None)

    def get_model_by_hash_typed(self, hash_value: str, force_refresh: bool = False) -> Optional[Model]:
        return self.get_model_by_hash(hash_value, force_refresh, typed=True)

    @overload
    def search_models(self, *, query: Optional[str] = None, tags: Optional[List[str]] = None,
                     username: Optional[str] = None, types: Optional[List[str]] = None,
                     sort: Optional[str] = None, period: Optional[str] = None,
                     nsfw: Optional[bool] = None, limit: int = 100, page: int = 1,
                     force_refresh: bool = False) -> Dict[str, Any]: ...
    @overload
    def search_models(self, *, query: Optional[str] = None, tags: Optional[List[str]] = None,
                     username: Optional[str] = None, types: Optional[List[str]] = None,
                     sort: Optional[str] = None, period: Optional[str] = None,
                     nsfw: Optional[bool] = None, limit: int = 100, page: int = 1,
                     force_refresh: bool = False, typed: bool = True) -> SearchResult: ...
    def search_models(self, *, query: Optional[str] = None, tags: Optional[List[str]] = None,
                     username: Optional[str] = None, types: Optional[List[str]] = None,
                     sort: Optional[str] = None, period: Optional[str] = None,
                     nsfw: Optional[bool] = None, limit: int = 100, page: int = 1,
                     force_refresh: bool = False, typed: bool = False) -> Union[Dict[str, Any], SearchResult]:
        return self._models.search(query=query, tags=tags, username=username, types=types,
                                 sort=sort, period=period, nsfw=nsfw, limit=limit,
                                 page=page, force_refresh=force_refresh,
                                 response_type=SearchResult if typed else None)

    def search_models_typed(self, **kwargs) -> SearchResult:
        return self.search_models(**kwargs, typed=True)

    @overload
    def get_model_version(self, version_id: int, force_refresh: bool = False) -> Dict[str, Any]: ...
    @overload
    def get_model_version(self, version_id: int, force_refresh: bool = False, typed: bool = True) -> ModelVersion: ...
    def get_model_version(self, version_id: int, force_refresh: bool = False, typed: bool = False) -> Union[Dict[str, Any], ModelVersion]:
        return self._versions.get(version_id, force_refresh=force_refresh, response_type=ModelVersion if typed else None)

    def get_model_version_typed(self, version_id: int, force_refresh: bool = False) -> ModelVersion:
        return self.get_model_version(version_id, force_refresh, typed=True)

    @overload
    def get_model_version_by_hash(self, hash_value: str, force_refresh: bool = False) -> Dict[str, Any]: ...
    @overload
    def get_model_version_by_hash(self, hash_value: str, force_refresh: bool = False, typed: bool = True) -> ModelVersion: ...
    def get_model_version_by_hash(self, hash_value: str, force_refresh: bool = False, typed: bool = False) -> Union[Dict[str, Any], ModelVersion]:
        return self._versions.get_by_hash(hash_value, force_refresh=force_refresh, response_type=ModelVersion if typed else None)

    def get_model_version_by_hash_typed(self, hash_value: str, force_refresh: bool = False) -> ModelVersion:
        return self.get_model_version_by_hash(hash_value, force_refresh, typed=True)

    def download_model(self, version_id: int, output_path: str) -> bool:
        """Download model file to the specified path."""
        return self._versions.download(version_id, output_path)

    @overload
    def get_images(self, *, model_id: Optional[int] = None, model_version_id: Optional[int] = None,
                  limit: int = 100, page: int = 1, force_refresh: bool = False) -> Dict[str, Any]: ...
    @overload
    def get_images(self, *, model_id: Optional[int] = None, model_version_id: Optional[int] = None,
                  limit: int = 100, page: int = 1, force_refresh: bool = False,
                  typed: bool = True) -> ImageSearchResult: ...
    def get_images(self, *, model_id: Optional[int] = None, model_version_id: Optional[int] = None,
                  limit: int = 100, page: int = 1, force_refresh: bool = False,
                  typed: bool = False) -> Union[Dict[str, Any], ImageSearchResult]:
        return self._images.get(model_id=model_id, model_version_id=model_version_id,
                              limit=limit, page=page, force_refresh=force_refresh,
                              response_type=ImageSearchResult if typed else None)

    def get_images_typed(self, **kwargs) -> ImageSearchResult:
        return self.get_images(**kwargs, typed=True)

    def download_image(self, url: str, output_path: str) -> Tuple[bool, Optional[str]]:
        """Download image from URL to the specified path."""
        return self._base_client.request_handler.download(url, output_path, dry_run=self._base_client.dry_run)

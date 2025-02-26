"""
CivitAI API client for CivitScraper.

This module handles communication with the CivitAI API, including:
- Authentication
- Rate limiting
- Caching
- Circuit breaker protection
"""

import os
import logging
from typing import Dict, Any, List, Optional, Union, TypeVar, Generic, Type

from .request import RequestHandler
from .response import ResponseParser
from .rate_limiter import RateLimiter
from .circuit_breaker import CircuitBreaker
from .exceptions import (
    CivitAIError,
    RateLimitError,
    CircuitBreakerOpenError,
    ClientError,
    ServerError,
    NetworkError,
    ParseError,
)
from .models import Model, ModelVersion, Image, SearchResult, ImageSearchResult
from ..utils.cache import CacheManager

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CivitAIClient:
    """
    Client for the CivitAI API.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize CivitAI API client.
        
        Args:
            config: API configuration
        """
        self.config = config
        self.base_url = config["api"]["base_url"]
        self.api_key = config["api"].get("key") or os.environ.get("CIVITAI_API_KEY")
        self.timeout = config["api"].get("timeout", 30)
        self.max_retries = config["api"].get("max_retries", 3)
        self.user_agent = config["api"].get("user_agent", "CivitScraper/0.1.0")
        
        # Get dry run flag
        self.dry_run = config.get("dry_run", False)
        
        # Set up rate limiting
        rate_limit = config["api"].get("batch", {}).get("rate_limit", 100)
        self.rate_limiter = RateLimiter(rate_limit)
        
        # Set up circuit breaker
        failure_threshold = config["api"].get("batch", {}).get("circuit_breaker", {}).get("failure_threshold", 5)
        reset_timeout = config["api"].get("batch", {}).get("circuit_breaker", {}).get("reset_timeout", 60)
        self.circuit_breaker = CircuitBreaker(failure_threshold, reset_timeout)
        
        # Set up retry delay (convert from ms to seconds)
        self.base_retry_delay = config["api"].get("batch", {}).get("retry_delay", 2000) / 1000.0
        
        # Set up cache
        cache_dir = config.get("scanner", {}).get("cache_dir", ".civitscraper_cache")
        cache_validity = config.get("scanner", {}).get("cache_validity", 86400)
        self.cache_manager = CacheManager(config)
        
        # Set up headers
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        
        # Add API key if available
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        # Create request handler
        self.request_handler = RequestHandler(
            base_url=self.base_url,
            rate_limiter=self.rate_limiter,
            circuit_breaker=self.circuit_breaker,
            cache_manager=self.cache_manager,
            timeout=self.timeout,
            max_retries=self.max_retries,
            base_retry_delay=self.base_retry_delay,
            headers=headers,
        )
        
        # Create response parser
        self.response_parser = ResponseParser()
        
        logger.debug(f"Initialized CivitAI API client for {self.base_url}")
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
        response_type: Optional[Type[T]] = None,
    ) -> Union[Dict[str, Any], T]:
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
            API response as dictionary or parsed object
            
        Raises:
            CivitAIError: If request fails
        """
        try:
            # Make request
            response_text = self.request_handler.request(
                method=method,
                endpoint=endpoint,
                params=params,
                data=data,
                force_refresh=force_refresh,
            )
            
            # Parse response
            if response_type:
                return self.response_parser.parse_response(response_text, response_type)
            else:
                return self.response_parser.parse_json(response_text)
        
        except CivitAIError:
            # Re-raise CivitAIError exceptions
            raise
        
        except Exception as e:
            # Wrap other exceptions
            logger.error(f"Error making request: {e}")
            raise NetworkError(str(e))
    
    def get_model(self, model_id: int, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get model by ID.
        
        Args:
            model_id: Model ID
            force_refresh: Force refresh cache
            
        Returns:
            Model data
        """
        return self._make_request("GET", f"models/{model_id}", force_refresh=force_refresh)
    
    def get_model_typed(self, model_id: int, force_refresh: bool = False) -> Model:
        """
        Get model by ID as a typed Model object.
        
        Args:
            model_id: Model ID
            force_refresh: Force refresh cache
            
        Returns:
            Model object
        """
        return self._make_request("GET", f"models/{model_id}", force_refresh=force_refresh, response_type=Model)
    
    def get_model_version(self, version_id: int, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get model version by ID.
        
        Args:
            version_id: Model version ID
            force_refresh: Force refresh cache
            
        Returns:
            Model version data
        """
        return self._make_request("GET", f"model-versions/{version_id}", force_refresh=force_refresh)
    
    def get_model_version_typed(self, version_id: int, force_refresh: bool = False) -> ModelVersion:
        """
        Get model version by ID as a typed ModelVersion object.
        
        Args:
            version_id: Model version ID
            force_refresh: Force refresh cache
            
        Returns:
            ModelVersion object
        """
        return self._make_request("GET", f"model-versions/{version_id}", force_refresh=force_refresh, response_type=ModelVersion)
    
    def get_model_version_by_hash(self, hash_value: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get model version by hash.
        
        Args:
            hash_value: Model hash
            force_refresh: Force refresh cache
            
        Returns:
            Model version data
        """
        return self._make_request("GET", f"model-versions/by-hash/{hash_value}", force_refresh=force_refresh)
    
    def get_model_version_by_hash_typed(self, hash_value: str, force_refresh: bool = False) -> ModelVersion:
        """
        Get model version by hash as a typed ModelVersion object.
        
        Args:
            hash_value: Model hash
            force_refresh: Force refresh cache
            
        Returns:
            ModelVersion object
        """
        return self._make_request("GET", f"model-versions/by-hash/{hash_value}", force_refresh=force_refresh, response_type=ModelVersion)
    
    def search_models(
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
    ) -> Dict[str, Any]:
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
            
        Returns:
            Search results
        """
        params = {
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
        
        return self._make_request("GET", "models", params=params, force_refresh=force_refresh)
    
    def search_models_typed(
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
    ) -> SearchResult:
        """
        Search models and return typed SearchResult object.
        
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
            
        Returns:
            SearchResult object
        """
        params = {
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
        
        return self._make_request("GET", "models", params=params, force_refresh=force_refresh, response_type=SearchResult)
    
    def get_images(
        self,
        model_id: Optional[int] = None,
        model_version_id: Optional[int] = None,
        limit: int = 100,
        page: int = 1,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Get images.
        
        Args:
            model_id: Filter by model ID
            model_version_id: Filter by model version ID
            limit: Results per page
            page: Page number
            force_refresh: Force refresh cache
            
        Returns:
            Images data
        """
        params = {
            "limit": limit,
            "page": page,
        }
        
        if model_id:
            params["modelId"] = model_id
        
        if model_version_id:
            params["modelVersionId"] = model_version_id
        
        return self._make_request("GET", "images", params=params, force_refresh=force_refresh)
    
    def get_images_typed(
        self,
        model_id: Optional[int] = None,
        model_version_id: Optional[int] = None,
        limit: int = 100,
        page: int = 1,
        force_refresh: bool = False,
    ) -> ImageSearchResult:
        """
        Get images as typed ImageSearchResult object.
        
        Args:
            model_id: Filter by model ID
            model_version_id: Filter by model version ID
            limit: Results per page
            page: Page number
            force_refresh: Force refresh cache
            
        Returns:
            ImageSearchResult object
        """
        params = {
            "limit": limit,
            "page": page,
        }
        
        if model_id:
            params["modelId"] = model_id
        
        if model_version_id:
            params["modelVersionId"] = model_version_id
        
        return self._make_request("GET", "images", params=params, force_refresh=force_refresh, response_type=ImageSearchResult)
    
    def download_image(self, url: str, output_path: str) -> tuple[bool, Optional[str]]:
        """
        Download image from URL.
        
        Args:
            url: Image URL
            output_path: Output file path
            
        Returns:
            Tuple of (success_status, content_type) where:
            - success_status: True if download was successful, False otherwise
            - content_type: The Content-Type of the downloaded file, or None if not available
        """
        return self.request_handler.download(url, output_path, dry_run=self.dry_run)
    
    def download_model(self, version_id: int, output_path: str) -> bool:
        """
        Download model file.
        
        Args:
            version_id: Model version ID
            output_path: Output file path
            
        Returns:
            True if download was successful, False otherwise
        """
        try:
            # Get model version
            version_data = self.get_model_version(version_id)
            
            # Get download URL
            download_url = version_data.get("downloadUrl")
            if not download_url:
                logger.error(f"No download URL found for model version {version_id}")
                return False
            
            # Download model
            return self.request_handler.download(download_url, output_path, dry_run=self.dry_run)
        
        except Exception as e:
            logger.error(f"Error downloading model: {e}")
            return False

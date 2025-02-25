"""
CivitAI API client for CivitScraper.

This module handles communication with the CivitAI API, including:
- Authentication
- Rate limiting
- Caching
- Circuit breaker protection
"""

import os
import time
import logging
import requests
from typing import Dict, Any, List, Optional, Union
import json
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter for API requests.
    """
    
    def __init__(self, rate_limit: int, per_second: bool = False):
        """
        Initialize rate limiter.
        
        Args:
            rate_limit: Maximum number of requests per minute (or per second if per_second is True)
            per_second: If True, rate_limit is per second, otherwise per minute
        """
        self.rate_limit = rate_limit
        self.per_second = per_second
        self.tokens = rate_limit
        self.last_refill = time.time()
        self.lock = threading.Lock()
        
        # Calculate token refill rate
        if per_second:
            self.refill_rate = rate_limit  # tokens per second
            self.refill_interval = 1.0  # seconds
        else:
            self.refill_rate = rate_limit / 60.0  # tokens per second
            self.refill_interval = 60.0  # seconds
    
    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        
        # Calculate tokens to add
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.rate_limit, self.tokens + new_tokens)
        self.last_refill = now
    
    def acquire(self, tokens: int = 1, block: bool = True) -> bool:
        """
        Acquire tokens from the bucket.
        
        Args:
            tokens: Number of tokens to acquire
            block: If True, block until tokens are available
            
        Returns:
            True if tokens were acquired, False otherwise
        """
        with self.lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            if not block:
                return False
            
            # Calculate wait time
            wait_time = (tokens - self.tokens) / self.refill_rate
            
            # Wait for tokens to become available
            time.sleep(wait_time)
            
            # Refill and acquire
            self._refill()
            self.tokens -= tokens
            return True


class CircuitBreaker:
    """
    Circuit breaker for API endpoints to prevent abuse during outages.
    """
    
    def __init__(self, failure_threshold: int, reset_timeout: int):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            reset_timeout: Seconds to wait before auto-recovery
        """
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = {}  # endpoint -> failure count
        self.open_circuits = {}  # endpoint -> open time
        self.lock = threading.Lock()
    
    def is_open(self, endpoint: str) -> bool:
        """
        Check if circuit is open for endpoint.
        
        Args:
            endpoint: API endpoint
            
        Returns:
            True if circuit is open, False otherwise
        """
        with self.lock:
            # Check if circuit is open
            if endpoint in self.open_circuits:
                open_time = self.open_circuits[endpoint]
                
                # Check if reset timeout has elapsed
                if time.time() - open_time >= self.reset_timeout:
                    # Reset circuit
                    del self.open_circuits[endpoint]
                    self.failures[endpoint] = 0
                    logger.info(f"Circuit breaker reset for endpoint: {endpoint}")
                    return False
                
                return True
            
            return False
    
    def record_failure(self, endpoint: str):
        """
        Record a failure for endpoint.
        
        Args:
            endpoint: API endpoint
        """
        with self.lock:
            # Initialize failure count
            if endpoint not in self.failures:
                self.failures[endpoint] = 0
            
            # Increment failure count
            self.failures[endpoint] += 1
            
            # Check if threshold is reached
            if self.failures[endpoint] >= self.failure_threshold:
                # Open circuit
                self.open_circuits[endpoint] = time.time()
                logger.warning(f"Circuit breaker opened for endpoint: {endpoint}")
    
    def record_success(self, endpoint: str):
        """
        Record a success for endpoint.
        
        Args:
            endpoint: API endpoint
        """
        with self.lock:
            # Reset failure count
            if endpoint in self.failures:
                self.failures[endpoint] = 0


class Cache:
    """
    Simple file-based cache for API responses.
    """
    
    def __init__(self, cache_dir: str, cache_validity: int):
        """
        Initialize cache.
        
        Args:
            cache_dir: Directory to store cache files
            cache_validity: Cache validity in seconds
        """
        self.cache_dir = Path(cache_dir)
        self.cache_validity = cache_validity
        
        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, key: str) -> Path:
        """
        Get cache file path for key.
        
        Args:
            key: Cache key
            
        Returns:
            Path to cache file
        """
        # Use hash of key as filename to avoid invalid characters
        filename = f"{hash(key)}.json"
        return self.cache_dir / filename
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found or expired
        """
        cache_path = self._get_cache_path(key)
        
        # Check if cache file exists
        if not cache_path.exists():
            return None
        
        # Check if cache is expired
        if time.time() - cache_path.stat().st_mtime > self.cache_validity:
            return None
        
        # Read cache file
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading cache file: {e}")
            return None
    
    def set(self, key: str, value: Any):
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        cache_path = self._get_cache_path(key)
        
        # Write cache file
        try:
            with open(cache_path, "w") as f:
                json.dump(value, f)
        except IOError as e:
            logger.error(f"Error writing cache file: {e}")


class CircuitBreakerOpenError(Exception):
    """Exception raised when circuit breaker is open."""
    pass


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
        self.base_url = config["api"]["base_url"]
        self.api_key = config["api"].get("key") or os.environ.get("CIVITAI_API_KEY")
        self.timeout = config["api"].get("timeout", 30)
        self.max_retries = config["api"].get("max_retries", 3)
        self.user_agent = config["api"].get("user_agent", "CivitScraper/0.1.0")
        
        # Set up rate limiting
        rate_limit = config["api"].get("batch", {}).get("rate_limit", 100)
        self.rate_limiter = RateLimiter(rate_limit)
        
        # Set up circuit breaker
        failure_threshold = config["api"].get("batch", {}).get("circuit_breaker", {}).get("failure_threshold", 5)
        reset_timeout = config["api"].get("batch", {}).get("circuit_breaker", {}).get("reset_timeout", 60)
        self.circuit_breaker = CircuitBreaker(failure_threshold, reset_timeout)
        
        # Set up cache
        cache_dir = config.get("scanner", {}).get("cache_dir", ".civitscaper_cache")
        cache_validity = config.get("scanner", {}).get("cache_validity", 86400)
        self.cache = Cache(cache_dir, cache_validity)
        
        # Set up session
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        })
        
        # Add API key if available
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
            })
    
    def _get_endpoint_name(self, url: str) -> str:
        """
        Get endpoint name from URL.
        
        Args:
            url: API URL
            
        Returns:
            Endpoint name
        """
        # Extract endpoint from URL
        path = url.replace(self.base_url, "").strip("/")
        parts = path.split("/")
        
        # Use first part as endpoint name
        if parts:
            return parts[0]
        
        return "unknown"
    
    def _make_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None,
                     data: Optional[Dict[str, Any]] = None, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Make API request with rate limiting, caching, and circuit breaker protection.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request data
            force_refresh: Force refresh cache
            
        Returns:
            API response
            
        Raises:
            CircuitBreakerOpenError: If circuit breaker is open
            requests.RequestException: If request fails
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        endpoint_name = self._get_endpoint_name(url)
        
        # Check circuit breaker
        if self.circuit_breaker.is_open(endpoint_name):
            raise CircuitBreakerOpenError(f"Circuit breaker open for endpoint: {endpoint_name}")
        
        # Check cache for GET requests
        cache_key = f"{method}:{url}:{json.dumps(params or {})}:{json.dumps(data or {})}"
        if method.upper() == "GET" and not force_refresh:
            cached_response = self.cache.get(cache_key)
            if cached_response:
                logger.debug(f"Cache hit for {url}")
                return cached_response
        
        # Acquire rate limit token
        self.rate_limiter.acquire()
        
        # Make request with retries
        retries = 0
        while retries <= self.max_retries:
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    timeout=self.timeout,
                )
                
                # Check for rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    logger.warning(f"Rate limited, retrying after {retry_after} seconds")
                    time.sleep(retry_after)
                    retries += 1
                    continue
                
                # Check for server errors
                if response.status_code >= 500:
                    self.circuit_breaker.record_failure(endpoint_name)
                    retries += 1
                    retry_delay = 2 ** retries  # Exponential backoff
                    logger.warning(f"Server error {response.status_code}, retrying after {retry_delay} seconds")
                    time.sleep(retry_delay)
                    continue
                
                # Check for client errors
                if response.status_code >= 400:
                    self.circuit_breaker.record_failure(endpoint_name)
                    raise requests.RequestException(f"Client error: {response.status_code} {response.text}")
                
                # Parse response
                response_data = response.json()
                
                # Record success
                self.circuit_breaker.record_success(endpoint_name)
                
                # Cache response for GET requests
                if method.upper() == "GET":
                    self.cache.set(cache_key, response_data)
                
                return response_data
            
            except (requests.RequestException, json.JSONDecodeError) as e:
                self.circuit_breaker.record_failure(endpoint_name)
                retries += 1
                
                if retries > self.max_retries:
                    raise
                
                retry_delay = 2 ** retries  # Exponential backoff
                logger.warning(f"Request failed: {e}, retrying after {retry_delay} seconds")
                time.sleep(retry_delay)
    
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
    
    def search_models(self, query: Optional[str] = None, tags: Optional[List[str]] = None,
                     username: Optional[str] = None, types: Optional[List[str]] = None,
                     sort: Optional[str] = None, period: Optional[str] = None,
                     nsfw: Optional[bool] = None, limit: int = 100, page: int = 1,
                     force_refresh: bool = False) -> Dict[str, Any]:
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
    
    def get_images(self, model_id: Optional[int] = None, model_version_id: Optional[int] = None,
                  limit: int = 100, page: int = 1, force_refresh: bool = False) -> Dict[str, Any]:
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
    
    def download_image(self, url: str, output_path: str) -> bool:
        """
        Download image from URL.
        
        Args:
            url: Image URL
            output_path: Output file path
            
        Returns:
            True if download was successful, False otherwise
        """
        try:
            # Acquire rate limit token
            self.rate_limiter.acquire()
            
            # Make request
            response = self.session.get(url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Save image
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
            return False
    
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
            
            # Acquire rate limit token
            self.rate_limiter.acquire()
            
            # Make request
            response = self.session.get(download_url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Save model file
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        
        except Exception as e:
            logger.error(f"Error downloading model: {e}")
            return False

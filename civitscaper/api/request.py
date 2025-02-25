"""
Request handler for CivitAI API client.

This module handles making HTTP requests with rate limiting, circuit breaking, and caching.
"""

import os
import time
import logging
import requests
from typing import Dict, Any, List, Optional, Union, Callable
import json

from .rate_limiter import RateLimiter
from .circuit_breaker import CircuitBreaker
from .exceptions import (
    RateLimitError,
    CircuitBreakerOpenError,
    ClientError,
    ServerError,
    NetworkError,
)
from ..utils.cache import CacheManager, DiskCache

logger = logging.getLogger(__name__)


class RequestHandler:
    """
    Handler for API requests with rate limiting, circuit breaking, and caching.
    """
    
    def __init__(
        self,
        base_url: str,
        rate_limiter: RateLimiter,
        circuit_breaker: CircuitBreaker,
        cache_manager: Optional[CacheManager] = None,
        timeout: int = 30,
        max_retries: int = 3,
        base_retry_delay: float = 2.0,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize request handler.
        
        Args:
            base_url: Base URL for API requests
            rate_limiter: Rate limiter instance
            circuit_breaker: Circuit breaker instance
            cache_manager: Cache manager instance (optional)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries
            base_retry_delay: Base retry delay in seconds
            headers: Additional headers to include in requests
        """
        self.base_url = base_url
        self.rate_limiter = rate_limiter
        self.circuit_breaker = circuit_breaker
        self.cache_manager = cache_manager
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        
        # Set up session
        self.session = requests.Session()
        
        # Set default headers
        self.session.headers.update({
            "Accept": "application/json",
        })
        
        # Add additional headers
        if headers:
            self.session.headers.update(headers)
        
        logger.debug(f"Initialized request handler for {base_url}")
    
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
    
    def _get_full_url(self, endpoint: str) -> str:
        """
        Get full URL for endpoint.
        
        Args:
            endpoint: API endpoint
            
        Returns:
            Full URL
        """
        return f"{self.base_url}/{endpoint.lstrip('/')}"
    
    def _get_cache_key(self, method: str, url: str, params: Optional[Dict[str, Any]] = None,
                      data: Optional[Dict[str, Any]] = None) -> str:
        """
        Get cache key for request.
        
        Args:
            method: HTTP method
            url: API URL
            params: Query parameters
            data: Request data
            
        Returns:
            Cache key
        """
        return f"{method}:{url}:{json.dumps(params or {})}:{json.dumps(data or {})}"
    
    def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
    ) -> str:
        """
        Make API request with rate limiting, caching, and circuit breaker protection.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request data
            force_refresh: Force refresh cache
            
        Returns:
            Response text
            
        Raises:
            CircuitBreakerOpenError: If circuit breaker is open
            RateLimitError: If rate limit is exceeded
            ClientError: If client error occurs (4xx)
            ServerError: If server error occurs (5xx)
            NetworkError: If network error occurs
        """
        url = self._get_full_url(endpoint)
        endpoint_name = self._get_endpoint_name(url)
        
        # Check circuit breaker
        if self.circuit_breaker.is_open(endpoint_name):
            raise CircuitBreakerOpenError(endpoint_name)
        
        # Check cache for GET requests
        cache_key = self._get_cache_key(method, url, params, data)
        if method.upper() == "GET" and not force_refresh and self.cache_manager:
            cached_response = self.cache_manager.get(cache_key)
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
                    
                    # Record failure
                    self.circuit_breaker.record_failure(endpoint_name)
                    
                    # If we've reached max retries, raise exception
                    if retries >= self.max_retries:
                        raise RateLimitError(retry_after)
                    
                    # Wait and retry
                    time.sleep(retry_after)
                    retries += 1
                    continue
                
                # Check for server errors
                if response.status_code >= 500:
                    self.circuit_breaker.record_failure(endpoint_name)
                    
                    # If we've reached max retries, raise exception
                    if retries >= self.max_retries:
                        raise ServerError(response.status_code, response.text)
                    
                    # Use exponential backoff
                    retry_delay = self.base_retry_delay * (2 ** retries)
                    logger.warning(f"Server error {response.status_code}, retrying after {retry_delay:.2f} seconds")
                    
                    # Wait and retry
                    time.sleep(retry_delay)
                    retries += 1
                    continue
                
                # Check for client errors
                if response.status_code >= 400:
                    self.circuit_breaker.record_failure(endpoint_name)
                    raise ClientError(response.status_code, response.text)
                
                # Record success
                self.circuit_breaker.record_success(endpoint_name)
                
                # Cache response for GET requests
                if method.upper() == "GET" and self.cache_manager:
                    self.cache_manager.set(cache_key, response.text)
                
                return response.text
            
            except (requests.RequestException, json.JSONDecodeError) as e:
                self.circuit_breaker.record_failure(endpoint_name)
                
                # If we've reached max retries, raise exception
                if retries >= self.max_retries:
                    raise NetworkError(str(e))
                
                # Use exponential backoff
                retry_delay = self.base_retry_delay * (2 ** retries)
                logger.warning(f"Request failed: {e}, retrying after {retry_delay:.2f} seconds")
                
                # Wait and retry
                time.sleep(retry_delay)
                retries += 1
        
        # This should never be reached, but just in case
        raise NetworkError("Maximum retries exceeded")
    
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, force_refresh: bool = False) -> str:
        """
        Make GET request.
        
        Args:
            endpoint: API endpoint
            params: Query parameters
            force_refresh: Force refresh cache
            
        Returns:
            Response text
        """
        return self.request("GET", endpoint, params=params, force_refresh=force_refresh)
    
    def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> str:
        """
        Make POST request.
        
        Args:
            endpoint: API endpoint
            data: Request data
            
        Returns:
            Response text
        """
        return self.request("POST", endpoint, data=data)
    
    def put(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> str:
        """
        Make PUT request.
        
        Args:
            endpoint: API endpoint
            data: Request data
            
        Returns:
            Response text
        """
        return self.request("PUT", endpoint, data=data)
    
    def delete(self, endpoint: str) -> str:
        """
        Make DELETE request.
        
        Args:
            endpoint: API endpoint
            
        Returns:
            Response text
        """
        return self.request("DELETE", endpoint)
    
    def download(self, url: str, output_path: str, dry_run: bool = False) -> bool:
        """
        Download file from URL.
        
        Args:
            url: File URL
            output_path: Output file path
            dry_run: If True, simulate download
            
        Returns:
            True if download was successful, False otherwise
        """
        # Check if in dry run mode
        if dry_run:
            logger.info(f"Dry run: Would download file from {url} to {output_path}")
            return True
        
        try:
            # Acquire rate limit token
            self.rate_limiter.acquire()
            
            # Make request
            response = self.session.get(url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Save file
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return False

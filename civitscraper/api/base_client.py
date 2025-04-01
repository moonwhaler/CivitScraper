"""Base client for CivitAI API.

This module provides the base client functionality for making API requests.
"""

import logging
import os
from typing import Any, Dict, Optional, Type, TypeVar

from ..utils.cache import CacheManager
from .circuit_breaker import CircuitBreaker
from .rate_limiter import RateLimiter
from .request import RequestHandler
from .response import ResponseParser

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseClient:
    """Base client for the CivitAI API."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize base client.

        Args:
            config: API configuration
        """
        self.config = config
        self.base_url = config["api"]["base_url"]
        self.api_key = config["api"].get("key") or os.environ.get("CIVITAI_API_KEY")
        self.timeout = config["api"].get("timeout", 30)
        self.max_retries = config["api"].get("max_retries", 3)
        self.user_agent = config["api"].get("user_agent", "CivitScraper/0.1.0")

        self.dry_run = config.get("dry_run", False)

        rate_limit = config["api"].get("batch", {}).get("rate_limit", 100)
        self.rate_limiter = RateLimiter(rate_limit)

        failure_threshold = (
            config["api"].get("batch", {}).get("circuit_breaker", {}).get("failure_threshold", 5)
        )
        reset_timeout = (
            config["api"].get("batch", {}).get("circuit_breaker", {}).get("reset_timeout", 60)
        )
        self.circuit_breaker = CircuitBreaker(failure_threshold, reset_timeout)

        # Convert ms to seconds
        self.base_retry_delay = config["api"].get("batch", {}).get("retry_delay", 2000) / 1000.0

        self.cache_manager: CacheManager[Any] = CacheManager(config)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

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

        self.response_parser = ResponseParser()

        logger.debug(f"Initialized CivitAI API base client for {self.base_url}")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
        response_type: Optional[Type[T]] = None,
    ) -> Any:
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
        """
        response_text = self.request_handler.request(
            method=method,
            endpoint=endpoint,
            params=params,
            data=data,
            force_refresh=force_refresh,
        )

        if response_type:
            return self.response_parser.parse_response(response_text, response_type)
        return self.response_parser.parse_json(response_text)

    def download(self, url: str, output_path: str) -> bool:
        """
        Download file from URL.

        Args:
            url: File URL
            output_path: Output file path

        Returns:
            True if download was successful, False otherwise
        """
        success, _ = self.request_handler.download(url, output_path, dry_run=self.dry_run)
        return success

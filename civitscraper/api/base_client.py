"""Base client for CivitAI API.

This module provides the base client functionality for making API requests.
"""

import logging
import os
from typing import Any, Dict, Optional

from .. import __version__
from ..utils.cache import CacheManager
from .circuit_breaker import CircuitBreaker
from .rate_limiter import RateLimiter
from .request import RequestHandler
from .response import parse_json

logger = logging.getLogger(__name__)


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
        self.user_agent = config["api"].get("user_agent", f"CivitScraper/{__version__}")

        self.dry_run = config.get("dry_run", False)

        rate_limit = config["api"].get("batch", {}).get("rate_limit", 100)
        self.rate_limiter = RateLimiter(rate_limit)
        download_rate_limit = config["api"].get("batch", {}).get("download_rate_limit", 300)
        self.download_rate_limiter = RateLimiter(download_rate_limit)

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
            download_rate_limiter=self.download_rate_limiter,
        )

        logger.debug(f"Initialized CivitAI API base client for {self.base_url}")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Make API request.

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request data
            force_refresh: Force refresh cache

        Returns:
            Parsed JSON response
        """
        response_text = self.request_handler.request(
            method=method,
            endpoint=endpoint,
            params=params,
            data=data,
            force_refresh=force_refresh,
        )

        return parse_json(response_text)

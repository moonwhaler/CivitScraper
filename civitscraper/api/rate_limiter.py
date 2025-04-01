"""
Rate limiter for CivitAI API client.

This module provides a token bucket rate limiter for API requests.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter for API requests."""

    def __init__(self, rate_limit: int, per_second: bool = False):
        """
        Initialize rate limiter.

        Args:
            rate_limit: Maximum number of requests per minute (or per second if per_second is True)
            per_second: If True, rate_limit is per second, otherwise per minute
        """
        self.rate_limit = rate_limit
        self.per_second = per_second
        self.tokens = float(rate_limit)
        self.last_refill = time.time()
        self.lock = threading.Lock()

        if per_second:
            self.refill_rate = float(rate_limit)
            self.refill_interval = 1.0
        else:
            self.refill_rate = float(rate_limit) / 60.0
            self.refill_interval = 60.0

        logger.debug(
            f"Initialized rate limiter with {rate_limit} requests per "
            f"{'second' if per_second else 'minute'}"
        )

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill

        new_tokens = elapsed * self.refill_rate
        self.tokens = min(float(self.rate_limit), self.tokens + new_tokens)
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

            wait_time = (tokens - self.tokens) / self.refill_rate

            logger.debug(f"Rate limit reached, waiting {wait_time: .2f} seconds for tokens")

            time.sleep(wait_time)

            self._refill()
            self.tokens -= tokens
            return True

    def get_tokens(self) -> float:
        """
        Get current number of tokens.

        Returns:
            Current number of tokens
        """
        with self.lock:
            self._refill()
            return self.tokens

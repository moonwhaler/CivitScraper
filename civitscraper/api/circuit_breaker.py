"""
Circuit breaker for CivitAI API client.

This module provides a circuit breaker to prevent abuse during API outages.
"""

import logging
import threading
import time
from typing import Dict

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker for API endpoints to prevent abuse during outages."""

    def __init__(self, failure_threshold: int, reset_timeout: int):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            reset_timeout: Seconds to wait before auto-recovery
        """
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures: Dict[str, int] = {}  # endpoint -> failure count
        self.open_circuits: Dict[str, float] = {}  # endpoint -> open time
        self.lock = threading.Lock()

        logger.debug(
            f"Initialized circuit breaker with failure threshold {failure_threshold} "
            f"and reset timeout {reset_timeout}s"
        )

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

    def get_failure_count(self, endpoint: str) -> int:
        """
        Get failure count for endpoint.

        Args:
            endpoint: API endpoint

        Returns:
            Failure count
        """
        with self.lock:
            return self.failures.get(endpoint, 0)

    def get_open_circuits(self) -> Dict[str, float]:
        """
        Get all open circuits.

        Returns:
            Dictionary of endpoint -> open time
        """
        with self.lock:
            return self.open_circuits.copy()

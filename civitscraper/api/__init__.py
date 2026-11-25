"""
CivitAI API client package.

This package provides a client for the CivitAI API.
"""

from .client import CivitAIClient
from .exceptions import (
    CircuitBreakerOpenError,
    CivitAIError,
    ClientError,
    NetworkError,
    ParseError,
    RateLimitError,
    ServerError,
)

__all__ = [
    # Client
    "CivitAIClient",
    # Exceptions
    "CivitAIError",
    "RateLimitError",
    "CircuitBreakerOpenError",
    "ClientError",
    "ServerError",
    "NetworkError",
    "ParseError",
]

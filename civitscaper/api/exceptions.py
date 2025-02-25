"""
Exceptions for CivitAI API client.

This module defines exceptions specific to the CivitAI API client.
"""

class CivitAIError(Exception):
    """Base exception for CivitAI API errors."""
    pass


class RateLimitError(CivitAIError):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(self, retry_after: int = 1):
        """
        Initialize rate limit error.
        
        Args:
            retry_after: Seconds to wait before retrying
        """
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")


class CircuitBreakerOpenError(CivitAIError):
    """Exception raised when circuit breaker is open."""
    
    def __init__(self, endpoint: str):
        """
        Initialize circuit breaker open error.
        
        Args:
            endpoint: API endpoint
        """
        self.endpoint = endpoint
        super().__init__(f"Circuit breaker open for endpoint: {endpoint}")


class ClientError(CivitAIError):
    """Exception raised for client errors (4xx)."""
    
    def __init__(self, status_code: int, message: str):
        """
        Initialize client error.
        
        Args:
            status_code: HTTP status code
            message: Error message
        """
        self.status_code = status_code
        super().__init__(f"Client error: {status_code} - {message}")


class ServerError(CivitAIError):
    """Exception raised for server errors (5xx)."""
    
    def __init__(self, status_code: int, message: str):
        """
        Initialize server error.
        
        Args:
            status_code: HTTP status code
            message: Error message
        """
        self.status_code = status_code
        super().__init__(f"Server error: {status_code} - {message}")


class ParseError(CivitAIError):
    """Exception raised when parsing API response fails."""
    
    def __init__(self, message: str):
        """
        Initialize parse error.
        
        Args:
            message: Error message
        """
        super().__init__(f"Failed to parse API response: {message}")


class NetworkError(CivitAIError):
    """Exception raised for network errors."""
    
    def __init__(self, message: str):
        """
        Initialize network error.
        
        Args:
            message: Error message
        """
        super().__init__(f"Network error: {message}")

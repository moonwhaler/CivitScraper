"""
Caching utilities for CivitScraper.

This module provides a more comprehensive caching system than the simple one in the API client.
"""

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LRUCache(Generic[T]):
    """LRU (Least Recently Used) cache implementation."""

    def __init__(self, capacity: int):
        """
        Initialize LRU cache.

        Args:
            capacity: Maximum number of items to store
        """
        self.capacity = capacity
        self.cache: Dict[str, Tuple[T, float]] = {}  # key -> (value, timestamp)
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[T]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        with self.lock:
            if key in self.cache:
                # Update timestamp
                value, _ = self.cache[key]
                self.cache[key] = (value, time.time())
                return value

            return None

    def put(self, key: str, value: T):
        """
        Put value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self.lock:
            # Add or update item
            self.cache[key] = (value, time.time())

            # Evict least recently used items if capacity is exceeded
            if len(self.cache) > self.capacity:
                # Find least recently used item
                oldest_key = min(self.cache.items(), key=lambda x: x[1][1])[0]

                # Remove item
                del self.cache[oldest_key]

    def remove(self, key: str):
        """
        Remove item from cache.

        Args:
            key: Cache key
        """
        with self.lock:
            if key in self.cache:
                del self.cache[key]

    def clear(self):
        """Clear cache."""
        with self.lock:
            self.cache.clear()

    def keys(self) -> List[str]:
        """
        Get list of keys in cache.

        Returns:
            List of keys
        """
        with self.lock:
            return list(self.cache.keys())

    def __len__(self) -> int:
        """
        Get number of items in cache.

        Returns:
            Number of items
        """
        with self.lock:
            return len(self.cache)


class DiskCache(Generic[T]):
    """Disk-based cache implementation."""

    def __init__(self, cache_dir: str, validity: int = 86400):
        """
        Initialize disk cache.

        Args:
            cache_dir: Directory to store cache files
            validity: Cache validity in seconds
        """
        self.cache_dir = Path(cache_dir)
        self.validity = validity
        self.memory_cache = LRUCache[T](1000)  # In-memory cache for frequently accessed items

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
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"

    def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """
        Get value from cache.

        Args:
            key: Cache key
            default: Default value if not found

        Returns:
            Cached value or default if not found or expired
        """
        # Check memory cache first
        value = self.memory_cache.get(key)
        if value is not None:
            return value

        # Check disk cache
        cache_path = self._get_cache_path(key)

        # Check if cache file exists
        if not cache_path.exists():
            return default

        # Check if cache is expired
        if time.time() - cache_path.stat().st_mtime > self.validity:
            return default

        # Read cache file
        try:
            with open(cache_path, "r") as f:
                value = json.load(f)

                # Add to memory cache
                self.memory_cache.put(key, value)

                return value if value is not None else default
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading cache file: {e}")
            return default

    def set(self, key: str, value: Any):
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        # Add to memory cache
        self.memory_cache.put(key, value)

        # Write to disk cache
        cache_path = self._get_cache_path(key)

        try:
            with open(cache_path, "w") as f:
                json.dump(value, f)
        except IOError as e:
            logger.error(f"Error writing cache file: {e}")

    def remove(self, key: str):
        """
        Remove item from cache.

        Args:
            key: Cache key
        """
        # Remove from memory cache
        self.memory_cache.remove(key)

        # Remove from disk cache
        cache_path = self._get_cache_path(key)

        try:
            if cache_path.exists():
                cache_path.unlink()
        except IOError as e:
            logger.error(f"Error removing cache file: {e}")

    def clear(self):
        """Clear cache."""
        # Clear memory cache
        self.memory_cache.clear()

        # Clear disk cache
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
        except IOError as e:
            logger.error(f"Error clearing cache: {e}")

    def clear_expired(self):
        """Clear expired cache items."""
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                # Check if cache is expired
                if time.time() - cache_file.stat().st_mtime > self.validity:
                    cache_file.unlink()
        except IOError as e:
            logger.error(f"Error clearing expired cache: {e}")

    def get_size(self) -> int:
        """
        Get total size of cache in bytes.

        Returns:
            Cache size in bytes
        """
        try:
            return sum(cache_file.stat().st_size for cache_file in self.cache_dir.glob("*.json"))
        except IOError as e:
            logger.error(f"Error getting cache size: {e}")
            return 0

    def get_item_count(self) -> int:
        """
        Get number of items in cache.

        Returns:
            Number of items
        """
        try:
            return len(list(self.cache_dir.glob("*.json")))
        except IOError as e:
            logger.error(f"Error getting cache item count: {e}")
            return 0


class CacheManager(Generic[T]):
    """Cache manager for CivitScraper."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize cache manager.

        Args:
            config: Cache configuration
        """
        self.config = config

        # Get cache directory
        cache_dir = config.get("scanner", {}).get("cache_dir", ".civitscraper_cache")

        # Get cache validity
        cache_validity = config.get("scanner", {}).get("cache_validity", 86400)

        # Create disk cache
        self.disk_cache = DiskCache[T](cache_dir, cache_validity)

        # Create memory cache
        memory_cache_size = config.get("api", {}).get("batch", {}).get("cache_size", 100)
        self.memory_cache = LRUCache[T](memory_cache_size)

    def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """
        Get value from cache.

        Args:
            key: Cache key
            default: Default value if not found

        Returns:
            Cached value or default if not found or expired
        """
        # Check memory cache first
        value = self.memory_cache.get(key)
        if value is not None:
            return value

        # Check disk cache
        value = self.disk_cache.get(key, default)

        # Add to memory cache if found
        if value is not default and value is not None:
            self.memory_cache.put(key, value)

        return value if value is not None else default

    def set(self, key: str, value: Any):
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        # Add to memory cache
        self.memory_cache.put(key, value)

        # Add to disk cache
        self.disk_cache.set(key, value)

    def remove(self, key: str):
        """
        Remove item from cache.

        Args:
            key: Cache key
        """
        # Remove from memory cache
        self.memory_cache.remove(key)

        # Remove from disk cache
        self.disk_cache.remove(key)

    def clear(self):
        """Clear cache."""
        # Clear memory cache
        self.memory_cache.clear()

        # Clear disk cache
        self.disk_cache.clear()

    def clear_expired(self):
        """Clear expired cache items."""
        self.disk_cache.clear_expired()

    def get_size(self) -> int:
        """
        Get total size of cache in bytes.

        Returns:
            Cache size in bytes
        """
        return self.disk_cache.get_size()

    def get_item_count(self) -> int:
        """
        Get number of items in cache.

        Returns:
            Number of items
        """
        return self.disk_cache.get_item_count()


def memoize(func: Callable[..., T]) -> Callable[..., T]:
    """
    Memoize decorator for caching function results.

    Args:
        func: Function to memoize

    Returns:
        Memoized function
    """
    cache: Dict[str, Any] = {}

    def wrapper(*args: Any, **kwargs: Any) -> T:
        # Create cache key
        key = str(args) + str(kwargs)

        # Check cache
        if key in cache:
            return cache[key]  # type: ignore

        # Call function
        result: T = func(*args, **kwargs)

        # Cache result
        cache[key] = result

        return result

    return wrapper

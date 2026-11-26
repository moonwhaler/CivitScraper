"""
Persistent cache of model file hashes.

Hashing a multi-GB model means reading all of it. A file whose size and
modification time (nanoseconds) are unchanged since it was last hashed is assumed
unchanged, so its hash is reused. Stored under ``<cache_dir>/file_hashes/`` (its
own directory: the API response cache prunes ``*.json`` files in ``<cache_dir>``).
"""

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from .fs import atomic_write

logger = logging.getLogger(__name__)

SAVE_EVERY = 250
_FORMAT_VERSION = 1


class HashCache:
    """Thread-safe (path, size, mtime) -> hash cache persisted as one JSON file."""

    def __init__(self, cache_dir: str):
        """
        Load the cache.

        Args:
            cache_dir: Scanner cache directory (``scanner.cache_dir``)
        """
        self.path = os.path.join(cache_dir, "file_hashes", "hashes.json")
        self._lock = threading.Lock()
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._unsaved = 0
        self._load()

    @staticmethod
    def _key(file_path: str, algorithm: str) -> str:
        return f"{algorithm.lower()}:{os.path.normcase(os.path.abspath(file_path))}"

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("version") == _FORMAT_VERSION:
                entries = data.get("entries", {})
                if isinstance(entries, dict):
                    self._entries = entries
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            logger.warning(f"Ignoring unreadable hash cache {self.path}: {e}")

    def get(self, file_path: str, algorithm: str, stat: os.stat_result) -> Optional[str]:
        """
        Return the cached hash if the file's size and mtime are unchanged.

        Args:
            file_path: Model file path
            algorithm: Hash algorithm
            stat: Current ``os.stat`` result for the file

        Returns:
            Cached hash or None
        """
        with self._lock:
            entry = self._entries.get(self._key(file_path, algorithm))
        if (
            entry
            and entry.get("size") == stat.st_size
            and entry.get("mtime_ns") == stat.st_mtime_ns
            and isinstance(entry.get("hash"), str)
        ):
            return str(entry["hash"])
        return None

    def put(self, file_path: str, algorithm: str, stat: os.stat_result, digest: str) -> None:
        """
        Record a freshly computed hash.

        Args:
            file_path: Model file path
            algorithm: Hash algorithm
            stat: ``os.stat`` result taken *before* hashing
            digest: Computed hash
        """
        with self._lock:
            self._entries[self._key(file_path, algorithm)] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "hash": digest,
            }
            self._unsaved += 1
            due = self._unsaved >= SAVE_EVERY
        if due:
            self.save()

    def rekey(self, old_path: str, new_path: str) -> None:
        """Move a renamed file's cached hashes (every algorithm) to its new path."""
        old_suffix = os.path.normcase(os.path.abspath(old_path))
        with self._lock:
            for key in [k for k in self._entries if k.split(":", 1)[-1] == old_suffix]:
                algorithm = key.split(":", 1)[0]
                self._entries[self._key(new_path, algorithm)] = self._entries.pop(key)
                self._unsaved += 1

    def save(self) -> None:
        """Persist the cache (atomic write); no-op when nothing changed."""
        with self._lock:
            if not self._unsaved:
                return
            payload = json.dumps(
                {"version": _FORMAT_VERSION, "entries": self._entries}, separators=(",", ":")
            )
            self._unsaved = 0
        try:
            atomic_write(self.path, payload)
        except OSError as e:
            logger.warning(f"Could not save hash cache {self.path}: {e}")


_instances: Dict[str, HashCache] = {}
_instances_lock = threading.Lock()


def get_hash_cache(config: Dict[str, Any]) -> HashCache:
    """Return the process-wide hash cache for the configured cache directory."""
    cache_dir = config.get("scanner", {}).get("cache_dir", ".civitscraper_cache")
    key = os.path.abspath(cache_dir)
    with _instances_lock:
        if key not in _instances:
            _instances[key] = HashCache(cache_dir)
        return _instances[key]

"""LRU and disk cache behaviour."""

import json
from unittest.mock import patch

from civitscraper.utils.cache import CacheManager, DiskCache, LRUCache


def test_lru_evicts_least_recently_used():
    """Reading an entry protects it; the oldest untouched one is evicted."""
    cache = LRUCache[int](2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.keys() == ["a", "c"]


def test_disk_cache_writes_atomically(tmp_path):
    """Entries go through atomic_write and read back after a restart."""
    with patch("civitscraper.utils.cache.atomic_write", wraps=__import__(
            "civitscraper.utils.fs", fromlist=["atomic_write"]).atomic_write) as spy:
        DiskCache[str](str(tmp_path)).set("k", "value")
    assert spy.call_count == 1
    assert DiskCache[str](str(tmp_path)).get("k") == "value"
    (entry,) = list(tmp_path.glob("*.json"))
    assert json.loads(entry.read_text()) == "value"


def test_cache_manager_keeps_one_memory_copy(tmp_path):
    """The api.batch.cache_size setting sizes the single memory layer."""
    manager = CacheManager({"scanner": {"cache_dir": str(tmp_path)},
                            "api": {"batch": {"cache_size": 3}}})
    manager.set("k", "v")
    assert manager.get("k") == "v"
    assert manager.disk_cache.memory_cache.capacity == 3
    assert not hasattr(manager, "memory_cache")

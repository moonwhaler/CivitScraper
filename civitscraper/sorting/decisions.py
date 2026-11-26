"""
Remembered sort decisions.

Answers that should not be asked again ("keep this file here", "this file is a
Flux LoRA", "Illustrious LoRAs go in SDXL") are stored in one JSON file.
A file is identified by its content, not its path, so a decision survives moves
and renames: its SHA256 (from the sidecar or the hash cache) when known, else a
BLAKE3 digest of its size, header and first megabyte.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import blake3

from ..utils.fs import atomic_write
from ..utils.hash_cache import get_hash_cache
from .classifier import Item

logger = logging.getLogger(__name__)

_FORMAT_VERSION = 1
_CONTENT_PREFIX_BYTES = 1024 * 1024

KEEP = "keep"


def decisions_path(config: Dict[str, Any]) -> str:
    """``sorting.decisions_file``, relative to the config file's directory."""
    configured = (config.get("sorting") or {}).get("decisions_file") or "sort-decisions.json"
    path = os.path.expanduser(str(configured))
    if not os.path.isabs(path):
        base = config.get("_config_dir") or os.getcwd()
        path = os.path.join(str(base), path)
    return os.path.abspath(path)


def file_key(item: Item, config: Dict[str, Any]) -> Optional[str]:
    """Content identity of a model file."""
    for entry in (item.metadata or {}).get("files") or []:
        sha = ((entry or {}).get("hashes") or {}).get("SHA256")
        if isinstance(sha, str) and sha:
            name = (entry or {}).get("name")
            if not name or name == os.path.basename(item.path):
                return f"sha256:{sha.lower()}"
    try:
        stat = os.stat(item.path)
    except OSError:
        return None
    cached = get_hash_cache(config).get(item.path, "sha256", stat)
    if cached:
        return f"sha256:{cached.lower()}"
    digest = blake3.blake3()
    digest.update(str(stat.st_size).encode())
    try:
        with open(item.path, "rb") as f:
            digest.update(f.read(_CONTENT_PREFIX_BYTES))
    except OSError:
        return None
    digest.update(item.fingerprint.header_bytes)
    return f"b3:{digest.hexdigest()}"


class Decisions:
    """Per-file answers and folder rules, persisted as JSON."""

    def __init__(self, path: str):
        """Load the decisions file (missing is fine)."""
        self.path = path
        self.files: Dict[str, Dict[str, Any]] = {}
        # family name ("lora", "checkpoint") -> base model -> folder name
        self.rules: Dict[str, Dict[str, str]] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            logger.warning(f"Ignoring unreadable sort decisions {self.path}: {e}")
            return
        if isinstance(data, dict):
            if isinstance(data.get("files"), dict):
                self.files = data["files"]
            if isinstance(data.get("rules"), dict):
                self.rules = data["rules"]

    def get(self, key: Optional[str]) -> Optional[Dict[str, Any]]:
        """Return the remembered decision for a file key."""
        return self.files.get(key) if key else None

    def remember(self, key: Optional[str], decision: str, name: str, **extra: Any) -> None:
        """Remember a decision for a file."""
        if not key:
            return
        self.files[key] = {"decision": decision, "name": name, "at": int(time.time()), **extra}
        self._dirty = True

    def add_rule(self, family_name: str, base: str, folder: str) -> None:
        """Remember which folder a base model goes in."""
        self.rules.setdefault(family_name, {})[base] = folder
        self._dirty = True

    def save(self) -> None:
        """Write the decisions file if anything changed."""
        if not self._dirty:
            return
        payload = json.dumps(
            {"version": _FORMAT_VERSION, "files": self.files, "rules": self.rules},
            indent=2,
            sort_keys=True,
        )
        atomic_write(self.path, payload + "\n")
        self._dirty = False

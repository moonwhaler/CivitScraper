"""
File hashing utilities for CivitScraper.

This module provides functions for computing file hashes using various algorithms.
"""

import hashlib
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Names handled here in addition to anything hashlib provides
_SPECIAL_ALGORITHMS = {"sha256", "autov2", "autov1", "blake3", "crc32"}


CHUNK_SIZE = 1024 * 1024  # 1 MiB: few syscalls, hashlib releases the GIL per chunk


def _hash_stream(f: Any, hasher: Any, chunk_size: int) -> None:
    """Feed a file object into a hashlib-style hasher in chunks."""
    buffer = bytearray(chunk_size)
    view = memoryview(buffer)
    while True:
        n = f.readinto(buffer)
        if not n:
            break
        hasher.update(view[:n])


def compute_file_hash(
    file_path: str, algorithm: str = "sha256", chunk_size: int = CHUNK_SIZE
) -> Optional[str]:
    """
    Compute hash of a file.

    Args:
        file_path: Path to the file
        algorithm: Hash algorithm (sha256, autov2, autov1, blake3, crc32, or any hashlib name)
        chunk_size: Read size in bytes

    Returns:
        Upper-case hexadecimal hash string, or None if the file is missing/unreadable
    """
    algorithm = algorithm.lower()
    if algorithm not in _SPECIAL_ALGORITHMS and algorithm not in hashlib.algorithms_available:
        logger.error(f"Unknown hash algorithm: {algorithm}")
        return None

    try:
        if not os.path.isfile(file_path):
            logger.error(f"File not found: {file_path}")
            return None

        with open(file_path, "rb") as f:
            if algorithm == "autov1":
                return str(hashlib.sha256(f.read(1024 * 1024)).hexdigest().upper())

            if algorithm == "crc32":
                import zlib

                crc = 0
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    crc = zlib.crc32(chunk, crc)
                return f"{crc & 0xFFFFFFFF:08X}"

            if algorithm == "blake3":
                try:
                    import blake3

                    hasher: Any = blake3.blake3()
                except ImportError:
                    logger.warning("blake3 module not installed, falling back to SHA-256")
                    hasher = hashlib.sha256()
            else:
                name = "sha256" if algorithm in ("sha256", "autov2") else algorithm
                if hasattr(hashlib, "file_digest"):  # Python 3.11+
                    return str(hashlib.file_digest(f, name).hexdigest().upper())
                hasher = hashlib.new(name)

            _hash_stream(f, hasher, chunk_size)
            return str(hasher.hexdigest().upper())

    except Exception as e:
        logger.error(f"Error computing hash for {file_path}: {e}")
        return None

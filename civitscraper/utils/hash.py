"""
File hashing utilities for CivitScraper.

This module provides functions for computing file hashes using various algorithms.
"""

import hashlib
import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Hash function type
# Removed HashFunction type alias to avoid mypy error


def sha256_hash(data: bytes) -> str:
    """Compute SHA-256 hash of data."""
    return str(hashlib.sha256(data).hexdigest().upper())


def blake3_hash(data: bytes) -> str:
    """Compute BLAKE3 hash of data."""
    try:
        import blake3

        return str(blake3.blake3(data).hexdigest().upper())
    except ImportError:
        logger.warning("blake3 module not installed, falling back to SHA-256")
        return sha256_hash(data)


def crc32_hash(data: bytes) -> str:
    """Compute CRC32 hash of data."""
    import zlib

    crc = zlib.crc32(data) & 0xFFFFFFFF
    return f"{crc:08X}"


def auto_v1_hash(data: bytes) -> str:
    """Compute AutoV1 hash of data."""
    return sha256_hash(data[: 1024 * 1024])


def auto_v2_hash(data: bytes) -> str:
    """Compute AutoV2 hash of data."""
    return sha256_hash(data)


def create_hash_function(name: str) -> Callable[[bytes], str]:
    """Create a hash function that always returns a string."""
    name = name.lower()
    result: Callable[[bytes], str]
    if name == "blake3":
        result = blake3_hash
    elif name == "crc32":
        result = crc32_hash
    elif name == "autov1":
        result = auto_v1_hash
    elif name == "autov2":
        result = auto_v2_hash
    else:
        result = sha256_hash
    return result


# Map of hash algorithms to hash functions
HASH_FUNCTIONS: Dict[str, Callable[[bytes], str]] = {
    name: create_hash_function(name) for name in ["sha256", "blake3", "crc32", "autov1", "autov2"]
}


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
    if algorithm not in HASH_FUNCTIONS and algorithm not in hashlib.algorithms_available:
        logger.error(f"Unknown hash algorithm: {algorithm}")
        return None

    try:
        if not os.path.isfile(file_path):
            logger.error(f"File not found: {file_path}")
            return None

        with open(file_path, "rb") as f:
            if algorithm == "autov1":
                return sha256_hash(f.read(1024 * 1024))

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


def compute_file_hashes(
    file_path: str, algorithms: Optional[List[str]] = None, chunk_size: int = CHUNK_SIZE
) -> Dict[str, str]:
    """
    Compute multiple hashes of a file.

    Args:
        file_path: Path to the file
        algorithms: List of hash algorithms to use
        chunk_size: Chunk size for reading file

    Returns:
        Dictionary of algorithm -> hash
    """
    if algorithms is None:
        algorithms = ["sha256", "blake3", "crc32", "autov1", "autov2"]

    result = {}
    for algorithm in algorithms:
        hash_value = compute_file_hash(file_path, algorithm, chunk_size)
        if hash_value:
            result[algorithm] = hash_value

    return result

"""
File hashing utilities for CivitScraper.

This module provides functions for computing file hashes using various algorithms.
"""

import hashlib
import logging
import os
from typing import Callable, Dict, List, Optional, cast

logger = logging.getLogger(__name__)

# Hash function type
# Removed HashFunction type alias to avoid mypy error


def sha256_hash(data: bytes) -> str:
    """Compute SHA-256 hash of data."""
    return hashlib.sha256(data).hexdigest().upper()


def blake3_hash(data: bytes) -> str:
    """Compute BLAKE3 hash of data."""
    try:
        import blake3
        return blake3.blake3(data).hexdigest().upper()
    except ImportError:
        logger.warning("blake3 module not installed, falling back to SHA-256")
        return sha256_hash(data)


def crc32_hash(data: bytes) -> str:
    """Compute CRC32 hash of data."""
    import zlib
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return f"{crc: 08X}"


def auto_v1_hash(data: bytes) -> str:
    """Compute AutoV1 hash of data."""
    return sha256_hash(data[: 1024 * 1024])


def auto_v2_hash(data: bytes) -> str:
    """Compute AutoV2 hash of data."""
    return sha256_hash(data)


# type: ignore[no-any-return]
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
    name: create_hash_function(name)
    for name in ["sha256", "blake3", "crc32", "autov1", "autov2"]
}


def compute_file_hash(
    file_path: str, algorithm: str = "sha256", chunk_size: int = 8192
) -> Optional[str]:
    """
    Compute hash of a file.

    Args:
        file_path: Path to the file
        algorithm: Hash algorithm to use
        chunk_size: Chunk size for reading file

    Returns:
        Hexadecimal hash string or None if file not found
    """
    # Get hash function with explicit type
    hash_func: Optional[Callable[[bytes], str]] = HASH_FUNCTIONS.get(algorithm.lower())
    if not hash_func:
        logger.error(f"Unknown hash algorithm: {algorithm}")
        return None

    try:
        # Check if file exists
        if not os.path.isfile(file_path):
            logger.error(f"File not found: {file_path}")
            return None

        # Get file size
        file_size = os.path.getsize(file_path)

        # For small files, read the entire file at once
        if file_size < 10 * 1024 * 1024:  # 10 MB
            with open(file_path, "rb") as f:
                data = f.read()
            return hash_func(data)

        # For large files, read in chunks
        with open(file_path, "rb") as f:
            if algorithm.lower() in ["autov1", "autov2"]:
                # For AutoV1/V2, we need to read specific parts of the file
                if algorithm.lower() == "autov1":
                    # Read first 1 MB
                    data = f.read(1024 * 1024)
                    return create_hash_function("sha256")(data)
                else:
                    # For AutoV2, we'll use the full SHA-256 hash for simplicity
                    hasher_obj = hashlib.sha256()
                    while True:
                        data = f.read(chunk_size)
                        if not data:
                            break
                        hasher_obj.update(data)
                    return hasher_obj.hexdigest().upper()
            else:
                # For other algorithms, use the hash function directly
                hash_instance = (
                    hashlib.new(algorithm.lower())
                    if algorithm.lower() in hashlib.algorithms_available
                    else hashlib.sha256()
                )

                while True:
                    data = f.read(chunk_size)
                    if not data:
                        break
                    hash_instance.update(data)
                
                # hexdigest() always returns str
                result: str = hash_instance.hexdigest()
                return result.upper()

    except Exception as e:
        logger.error(f"Error computing hash for {file_path}: {e}")
        return None


def compute_file_hashes(
    file_path: str, algorithms: Optional[List[str]] = None, chunk_size: int = 8192
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

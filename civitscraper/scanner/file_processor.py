"""
Model file processor for CivitScraper.

This module handles processing individual model files, including hash computation and validation.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..utils.hash import compute_file_hash
from ..utils.hash_cache import get_hash_cache

logger = logging.getLogger(__name__)


@dataclass
class FileProcessingResult:
    """Result of processing a model file."""

    file_path: str
    file_hash: Optional[str]
    success: bool
    error: Optional[str] = None


class ModelFileProcessor:
    """
    Processor for individual model files.

    This class handles operations on individual model files, such as
    computing file hashes and validating files.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize model file processor.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.hash_cache = get_hash_cache(config)
        # --rehash: ignore cached hashes (fresh hashes are still recorded)
        self.rehash = bool(config.get("scanner", {}).get("rehash", False))

    def process(self, file_path: str, verify_hash: bool = True) -> FileProcessingResult:
        """
        Process a model file.

        Args:
            file_path: Path to model file
            verify_hash: Whether to verify file hash

        Returns:
            FileProcessingResult with processing results
        """
        # Check if file exists
        if not os.path.isfile(file_path):
            logger.error(f"File not found: {file_path}")
            return FileProcessingResult(
                file_path=file_path, file_hash=None, success=False, error="File not found"
            )

        # Compute file hash if needed
        file_hash = None
        if verify_hash:
            file_hash = self._hash(file_path)
            if not file_hash:
                logger.error(f"Failed to compute hash for {file_path}")
                return FileProcessingResult(
                    file_path=file_path,
                    file_hash=None,
                    success=False,
                    error="Failed to compute hash",
                )

        # Return successful result
        return FileProcessingResult(file_path=file_path, file_hash=file_hash, success=True)

    def _hash(self, file_path: str, algorithm: str = "sha256") -> Optional[str]:
        """Hash a file, reusing the cached hash when size and mtime are unchanged."""
        try:
            before = os.stat(file_path)
        except OSError:
            return None

        if not self.rehash:
            cached = self.hash_cache.get(file_path, algorithm, before)
            if cached:
                logger.debug(f"Using cached hash for {file_path}")
                return cached

        logger.debug(f"Computing hash for {file_path}")
        digest = compute_file_hash(file_path, algorithm)
        if not digest:
            return None

        # Only cache when the file did not change while it was read (e.g. still
        # being downloaded or copied).
        try:
            after = os.stat(file_path)
        except OSError:
            return digest
        if (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns):
            self.hash_cache.put(file_path, algorithm, before, digest)
        return digest

    def flush(self) -> None:
        """Persist newly computed hashes."""
        self.hash_cache.save()

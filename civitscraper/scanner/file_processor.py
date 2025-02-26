"""
Model file processor for CivitScraper.

This module handles processing individual model files, including hash computation and validation.
"""

import os
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from ..utils.hash import compute_file_hash

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
                file_path=file_path,
                file_hash=None,
                success=False,
                error="File not found"
            )
        
        # Compute file hash if needed
        file_hash = None
        if verify_hash:
            logger.debug(f"Computing hash for {file_path}")
            file_hash = compute_file_hash(file_path)
            if not file_hash:
                logger.error(f"Failed to compute hash for {file_path}")
                return FileProcessingResult(
                    file_path=file_path,
                    file_hash=None,
                    success=False,
                    error="Failed to compute hash"
                )
        
        # Return successful result
        return FileProcessingResult(
            file_path=file_path,
            file_hash=file_hash,
            success=True
        )

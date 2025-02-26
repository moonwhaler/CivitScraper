"""
Batch processor for CivitScraper.

This module handles batch processing of model files.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple, Callable

from ..utils.logging import BatchProgressTracker

logger = logging.getLogger(__name__)


class BatchProcessor:
    """
    Processor for batch operations.
    
    This class handles batch processing of model files.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize batch processor.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        
        # Get batch configuration
        self.batch_config = config.get("api", {}).get("batch", {})
    
    def process_in_batches(
        self,
        files: List[str],
        processor: Any,
        verify_hash: bool = True,
        force_refresh: bool = False,
        max_workers: Optional[int] = None,
        batch_size: int = 100
    ) -> List[Tuple[str, Optional[Dict[str, Any]]]]:
        """
        Process multiple model files in batches.
        
        Args:
            files: List of file paths
            processor: ModelProcessor instance
            verify_hash: Whether to verify file hash
            force_refresh: Whether to force refresh metadata
            max_workers: Maximum number of worker threads
            batch_size: Batch size
            
        Returns:
            List of (file_path, metadata) tuples
        """
        # Get batch processing configuration
        batch_enabled = self.batch_config.get("enabled", True)
        max_concurrent = self.batch_config.get("max_concurrent", 4)
        
        # Use default max_workers if not specified
        if max_workers is None:
            max_workers = max_concurrent if batch_enabled else 1
        
        # Calculate number of batches
        num_batches = (len(files) + batch_size - 1) // batch_size
        
        # Create batch progress tracker
        progress_tracker = BatchProgressTracker(logger, num_batches, len(files), "Processing model files")
        
        # Process files in batches
        results = []
        
        for batch_index in range(num_batches):
            # Get batch files
            start_index = batch_index * batch_size
            end_index = min(start_index + batch_size, len(files))
            batch_files = files[start_index:end_index]
            
            # Start batch
            progress_tracker.start_batch(batch_index + 1, len(batch_files))
            
            # Process batch
            batch_results = processor.process_files(batch_files, verify_hash, force_refresh, max_workers)
            
            # Update progress
            for _, metadata in batch_results:
                progress_tracker.update(metadata is not None)
            
            # Add batch results to results
            results.extend(batch_results)
            
            # End batch
            progress_tracker.end_batch()
        
        # End tracking
        progress_tracker.end()
        
        return results

"""
Model processor for CivitScraper.

This module handles processing model files, fetching metadata from the CivitAI API, and saving the metadata.
"""

import logging
import concurrent.futures
from typing import Dict, Any, List, Optional, Tuple, Set, Callable
from pathlib import Path
from dataclasses import dataclass

from ..api.client import CivitAIClient
from .metadata_manager import MetadataManager
from .image_manager import ImageManager
from .html_manager import HTMLManager
from .file_processor import ModelFileProcessor, FileProcessingResult
from .batch_processor import BatchProcessor
from ..utils.logging import ProgressLogger

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a model file."""
    file_path: str
    metadata: Optional[Dict[str, Any]]
    success: bool
    error: Optional[str] = None


class ModelProcessor:
    """
    Processor for model files.
    
    This class coordinates the overall process of processing model files,
    delegating specific tasks to specialized manager classes.
    """
    
    def __init__(self, config: Dict[str, Any], api_client: CivitAIClient, html_generator=None):
        """
        Initialize model processor.
        
        Args:
            config: Configuration dictionary
            api_client: CivitAI API client
            html_generator: HTML generator instance (optional)
        """
        self.config = config
        self.api_client = api_client
        
        # Get dry run flag
        self.dry_run = config.get("dry_run", False)
        
        # Initialize managers
        self.metadata_manager = MetadataManager(config, api_client)
        self.image_manager = ImageManager(config, api_client)
        self.html_manager = HTMLManager(config, html_generator)
        self.file_processor = ModelFileProcessor(config)
        self.batch_processor = BatchProcessor(config)
        
        # Initialize failure tracking
        self.failures: List[Tuple[str, str]] = []
    
    def process_file(self, file_path: str, verify_hash: bool = True, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Process a model file.
        
        Args:
            file_path: Path to model file
            verify_hash: Whether to verify file hash
            force_refresh: Whether to force refresh metadata
            
        Returns:
            Metadata or None if processing failed
        """
        try:
            # Process the file
            result = self.file_processor.process(file_path, verify_hash)
            if not result.success:
                self.failures.append((file_path, result.error or "Unknown error"))
                return None
            
            # Get metadata from API
            metadata = self.metadata_manager.fetch_and_save(
                file_path, 
                result.file_hash, 
                force_refresh=force_refresh,
                dry_run=self.dry_run
            )
            
            if not metadata:
                self.failures.append((file_path, "Failed to fetch metadata"))
                return None
            
            # Download images if configured
            if self.config.get("output", {}).get("images", {}).get("save", True):
                self.image_manager.download_images(file_path, metadata)
            
            # Generate HTML if configured
            if self.config.get("output", {}).get("metadata", {}).get("html", {}).get("enabled", True):
                self.html_manager.generate_html(file_path, metadata)
            
            return metadata
        
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            self.failures.append((file_path, f"Error processing: {e}"))
            return None
    
    def process_files(self, files: List[str], verify_hash: bool = True, force_refresh: bool = False,
                     max_workers: Optional[int] = None) -> List[Tuple[str, Optional[Dict[str, Any]]]]:
        """
        Process multiple model files.
        
        Args:
            files: List of file paths
            verify_hash: Whether to verify file hash
            force_refresh: Whether to force refresh metadata
            max_workers: Maximum number of worker threads
            
        Returns:
            List of (file_path, metadata) tuples
        """
        # Clear failures
        self.failures = []
        
        # Get batch processing configuration
        batch_config = self.config.get("api", {}).get("batch", {})
        batch_enabled = batch_config.get("enabled", True)
        max_concurrent = batch_config.get("max_concurrent", 4)
        
        # Use default max_workers if not specified
        if max_workers is None:
            max_workers = max_concurrent if batch_enabled else 1
        
        # Create progress logger
        progress_logger = ProgressLogger(logger, len(files), "Processing model files")
        
        # Process files
        results = []
        
        if max_workers > 1:
            # Process files in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit tasks
                future_to_file = {
                    executor.submit(self.process_file, file_path, verify_hash, force_refresh): file_path
                    for file_path in files
                }
                
                # Process results as they complete
                for future in concurrent.futures.as_completed(future_to_file):
                    file_path = future_to_file[future]
                    try:
                        metadata = future.result()
                        results.append((file_path, metadata))
                    except Exception as e:
                        logger.error(f"Error processing {file_path}: {e}")
                        self.failures.append((file_path, f"Error processing: {e}"))
                        results.append((file_path, None))
                    
                    # Update progress
                    progress_logger.update()
        else:
            # Process files sequentially
            for file_path in files:
                metadata = self.process_file(file_path, verify_hash, force_refresh)
                results.append((file_path, metadata))
                
                # Update progress
                progress_logger.update()
        
        # Log failures
        if self.failures:
            logger.warning(f"Failed to process {len(self.failures)} files")
            for file_path, error in self.failures:
                logger.debug(f"Failed to process {file_path}: {error}")
        
        return results
    
    def process_files_in_batches(self, files: List[str], verify_hash: bool = True, force_refresh: bool = False,
                               max_workers: Optional[int] = None, batch_size: int = 100) -> List[Tuple[str, Optional[Dict[str, Any]]]]:
        """
        Process multiple model files in batches.
        
        Args:
            files: List of file paths
            verify_hash: Whether to verify file hash
            force_refresh: Whether to force refresh metadata
            max_workers: Maximum number of worker threads
            batch_size: Batch size
            
        Returns:
            List of (file_path, metadata) tuples
        """
        return self.batch_processor.process_in_batches(
            files=files,
            processor=self,
            verify_hash=verify_hash,
            force_refresh=force_refresh,
            max_workers=max_workers,
            batch_size=batch_size
        )
    
    def get_failures(self) -> List[Tuple[str, str]]:
        """
        Get list of failures.
        
        Returns:
            List of (file_path, error) tuples
        """
        return self.failures

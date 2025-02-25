"""
Model processor for CivitScraper.

This module handles processing model files, fetching metadata from the CivitAI API, and saving the metadata.
"""

import os
import json
import logging
import concurrent.futures
from typing import Dict, Any, List, Optional, Tuple, Set, Callable

from ..api.client import CivitAIClient
from ..api.models import Model, ModelVersion
from ..utils.hash import compute_file_hash
from ..utils.logging import ProgressLogger, BatchProgressTracker
from .discovery import get_metadata_path, get_html_path, get_image_path

logger = logging.getLogger(__name__)


class ModelProcessor:
    """
    Processor for model files.
    """
    
    def __init__(self, config: Dict[str, Any], api_client: CivitAIClient, html_generator=None):
        """
        Initialize model processor.
        
        Args:
            config: Configuration
            api_client: CivitAI API client
            html_generator: HTML generator instance (optional)
        """
        self.config = config
        self.api_client = api_client
        self.html_generator = html_generator
        
        # Get scanner configuration
        self.scanner_config = config.get("scanner", {})
        
        # Get output configuration
        self.output_config = config.get("output", {})
        
        # Get batch configuration
        self.batch_config = config.get("api", {}).get("batch", {})
        
        # Initialize failure tracking
        self.failures = []
    
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
            # Compute file hash
            if verify_hash:
                logger.debug(f"Computing hash for {file_path}")
                file_hash = compute_file_hash(file_path)
                if not file_hash:
                    logger.error(f"Failed to compute hash for {file_path}")
                    self.failures.append((file_path, "Failed to compute hash"))
                    return None
            else:
                file_hash = None
            
            # Get metadata from API
            if file_hash:
                logger.debug(f"Fetching metadata for {file_path} with hash {file_hash}")
                try:
                    metadata = self.api_client.get_model_version_by_hash(file_hash, force_refresh=force_refresh)
                except Exception as e:
                    logger.error(f"Failed to fetch metadata for {file_path}: {e}")
                    self.failures.append((file_path, f"Failed to fetch metadata: {e}"))
                    return None
            else:
                logger.warning(f"Skipping metadata fetch for {file_path} (no hash)")
                return None
            
            # Save metadata
            metadata_path = get_metadata_path(file_path, self.config)
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
            
            # Save metadata
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
            
            logger.debug(f"Saved metadata to {metadata_path}")
            
            # Download images
            if self.output_config.get("images", {}).get("save", True):
                self._download_images(file_path, metadata)
            
            # Generate HTML
            if self.output_config.get("metadata", {}).get("html", {}).get("enabled", True):
                self._generate_html(file_path, metadata)
            
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
        batch_enabled = self.batch_config.get("enabled", True)
        max_concurrent = self.batch_config.get("max_concurrent", 4)
        
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
        # Clear failures
        self.failures = []
        
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
            batch_results = self.process_files(batch_files, verify_hash, force_refresh, max_workers)
            
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
    
    def _download_images(self, file_path: str, metadata: Dict[str, Any]):
        """
        Download images for model.
        
        Args:
            file_path: Path to model file
            metadata: Model metadata
        """
        # Get image configuration
        image_config = self.output_config.get("images", {})
        
        # Get maximum number of images to download
        max_count = image_config.get("max_count", 4)
        
        # Get images
        images = metadata.get("images", [])
        
        # Limit number of images
        images = images[:max_count]
        
        # Download images
        for i, image in enumerate(images):
            # Get image URL
            image_url = image.get("url")
            if not image_url:
                continue
            
            # Get image extension
            ext = os.path.splitext(image_url)[1]
            
            # Get image path with index
            image_path = get_image_path(file_path, self.config, f"preview{i}", ext)
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            
            # Download image
            logger.debug(f"Downloading image {i+1}/{len(images)} for {file_path}")
            success = self.api_client.download_image(image_url, image_path)
            
            if not success:
                logger.warning(f"Failed to download image {i+1}/{len(images)} for {file_path}")
    
    def _generate_html(self, file_path: str, metadata: Dict[str, Any]):
        """
        Generate HTML for model.
        
        Args:
            file_path: Path to model file
            metadata: Model metadata
        """
        logger.debug(f"Generating HTML for {file_path}")
        
        # Use HTMLGenerator if available
        if self.html_generator:
            # Generate HTML using the HTMLGenerator
            html_path = self.html_generator.generate_html(file_path, metadata)
            logger.debug(f"Generated HTML using templates at {html_path}")
        else:
            # Fallback to simple HTML generation
            html_path = get_html_path(file_path, self.config)
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(html_path), exist_ok=True)
            
            # Generate simple HTML
            with open(html_path, "w") as f:
                f.write(f"<html><head><title>{metadata.get('name', 'Model')}</title></head><body>")
                f.write(f"<h1>{metadata.get('name', 'Model')}</h1>")
                f.write(f"<p>Type: {metadata.get('model', {}).get('type', 'Unknown')}</p>")
                f.write(f"<p>Description: {metadata.get('description', 'No description')}</p>")
                f.write("</body></html>")
            
            logger.debug(f"Saved simple HTML to {html_path} (HTMLGenerator not available)")
    
    def get_failures(self) -> List[Tuple[str, str]]:
        """
        Get list of failures.
        
        Returns:
            List of (file_path, error) tuples
        """
        return self.failures

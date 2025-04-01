"""
Model processor for CivitScraper.

This module handles processing model files, fetching metadata from the CivitAI API,
and saving the metadata.
"""

import concurrent.futures
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..api.client import CivitAIClient
from ..utils.logging import ProgressLogger
from .batch_processor import BatchProcessor
from .discovery import get_metadata_path
from .file_processor import ModelFileProcessor
from .html_manager import HTMLManager
from .image_manager import ImageManager
from .metadata_manager import MetadataManager

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

        self.dry_run = config.get("dry_run", False)

        self.metadata_manager = MetadataManager(config, api_client)
        self.image_manager = ImageManager(config, api_client)
        self.html_manager = HTMLManager(config, html_generator)
        self.file_processor = ModelFileProcessor(config)
        self.batch_processor = BatchProcessor(config)

        self.failures: List[Tuple[str, str]] = []

    def fetch_metadata(
        self, file_path: str, verify_hash: bool = True, force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch metadata for a model file without saving to disk or generating HTML/images.

        Args:
            file_path: Path to model file
            verify_hash: Whether to verify file hash
            force_refresh: Whether to force refresh metadata

        Returns:
            Metadata or None if fetching failed
        """
        try:
            result = self.file_processor.process(file_path, verify_hash)
            if not result.success:
                self.failures.append((file_path, result.error or "Unknown error"))
                return None

            if result.file_hash is None:
                self.failures.append((file_path, "No file hash available"))
                return None

            metadata = self.metadata_manager.fetch_metadata(
                result.file_hash, force_refresh=force_refresh
            )

            if not metadata:
                self.failures.append((file_path, "Failed to fetch metadata"))
                return None

            return metadata

        except Exception as e:
            logger.error(f"Error fetching metadata for {file_path}: {e}")
            self.failures.append((file_path, f"Error fetching metadata: {e}"))
            return None

    def save_and_process_with_metadata(
        self, file_path: str, metadata: Dict[str, Any], force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Save metadata and process a model file with already fetched metadata.

        Args:
            file_path: Path to model file
            metadata: Pre-fetched metadata
            force_refresh: Whether to force refresh all data

        Returns:
            Metadata or None if processing failed
        """
        try:
            # Save metadata to disk - skip_existing is handled inside the method
            if not self.metadata_manager.save_metadata(file_path, metadata, self.dry_run):
                self.failures.append((file_path, "Failed to save metadata"))
                return None

            if self.config.get("output", {}).get("images", {}).get("save", True):
                # Always pass dry_run flag to ensure consistent behavior
                self.image_manager.download_images(file_path, metadata, force_refresh=force_refresh)

            html_enabled = (
                self.config.get("output", {})
                .get("metadata", {})
                .get("html", {})
                .get("enabled", True)
            )

            # Generate HTML if enabled. html_manager handles skip/refresh logic.
            if html_enabled:
                self.html_manager.generate_html(file_path, metadata, force_refresh=force_refresh)

            return metadata

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            self.failures.append((file_path, f"Error processing: {e}"))
            return None

    def process_file(
        self, file_path: str, verify_hash: bool = True, force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Process a model file (fetches metadata and processes in one step).

        Args:
            file_path: Path to model file
            verify_hash: Whether to verify file hash
            force_refresh: Whether to force refresh metadata

        Returns:
            Metadata or None if processing failed
        """
        try:
            skip_existing = self.config.get("skip_existing", False)

            metadata_path = get_metadata_path(file_path, self.config)
            if skip_existing and not force_refresh and os.path.exists(metadata_path):
                try:
                    with open(metadata_path, "r") as f:
                        metadata = json.load(f)

                    # Process with the loaded metadata - this will handle HTML and images properly
                    return self.save_and_process_with_metadata(
                        file_path, metadata, force_refresh=force_refresh
                    )
                except Exception as e:
                    logger.error(f"Error loading existing metadata for {file_path}: {e}")
                    # Fall through to full processing

            metadata = self.fetch_metadata(file_path, verify_hash, force_refresh)
            if not metadata:
                return None

            return self.save_and_process_with_metadata(
                file_path, metadata, force_refresh=force_refresh
            )

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            self.failures.append((file_path, f"Error processing: {e}"))
            return None

    def process_files(
        self,
        files: List[str],
        verify_hash: bool = True,
        force_refresh: bool = False,
        max_workers: Optional[int] = None,
    ) -> List[Tuple[str, Optional[Dict[str, Any]]]]:
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
        self.failures = []

        batch_config = self.config.get("api", {}).get("batch", {})
        batch_enabled = batch_config.get("enabled", True)
        max_concurrent = batch_config.get("max_concurrent", 4)

        if max_workers is None:
            max_workers = max_concurrent if batch_enabled else 1

        progress_logger = ProgressLogger(logger, len(files), "Processing model files")

        results = []

        if max_workers > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {
                    executor.submit(
                        self.process_file, file_path, verify_hash, force_refresh
                    ): file_path
                    for file_path in files
                }

                for future in concurrent.futures.as_completed(future_to_file):
                    file_path = future_to_file[future]
                    try:
                        metadata = future.result()
                        results.append((file_path, metadata))
                    except Exception as e:
                        logger.error(f"Error processing {file_path}: {e}")
                        self.failures.append((file_path, f"Error processing: {e}"))
                        results.append((file_path, None))

                    progress_logger.update()
        else:
            for file_path in files:
                metadata = self.process_file(file_path, verify_hash, force_refresh)
                results.append((file_path, metadata))

                progress_logger.update()

        if self.failures:
            logger.warning(f"Failed to process {len(self.failures)} files")
            for file_path, error in self.failures:
                logger.debug(f"Failed to process {file_path}: {error}")

        return results

    def process_files_in_batches(
        self,
        files: List[str],
        verify_hash: bool = True,
        force_refresh: bool = False,
        max_workers: Optional[int] = None,
        batch_size: int = 100,
    ) -> List[Tuple[str, Optional[Dict[str, Any]]]]:
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
            batch_size=batch_size,
        )

    def get_failures(self) -> List[Tuple[str, str]]:
        """
        Get list of failures.

        Returns:
            List of (file_path, error) tuples
        """
        return self.failures

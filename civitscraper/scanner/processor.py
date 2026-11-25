"""
Model processor for CivitScraper.

This module writes a model's outputs (sidecar, previews, detail page) from
already-fetched metadata.
"""

import logging
from typing import Any, Dict, Optional

from ..api.client import CivitAIClient
from .file_processor import ModelFileProcessor
from .html_manager import HTMLManager
from .image_manager import ImageManager
from .metadata_manager import MetadataManager

logger = logging.getLogger(__name__)


class ModelProcessor:
    """
    Processor for model files.

    This class coordinates the overall process of processing model files,
    delegating specific tasks to specialized manager classes.
    """

    def __init__(self, config: Dict[str, Any], api_client: CivitAIClient, html_generator: Any):
        """
        Initialize model processor.

        Args:
            config: Configuration dictionary
            api_client: CivitAI API client
            html_generator: HTML generator used for detail pages
        """
        self.config = config
        self.api_client = api_client

        self.dry_run = config.get("dry_run", False)

        self.metadata_manager = MetadataManager(config, api_client)
        self.image_manager = ImageManager(config, api_client)
        self.html_manager = HTMLManager(config, html_generator)
        self.file_processor = ModelFileProcessor(config)

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
            return None

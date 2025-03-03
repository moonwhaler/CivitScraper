"""
Metadata manager for CivitScraper.

This module handles fetching metadata from the CivitAI API and saving it to disk.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from ..api.client import CivitAIClient
from ..api.models import ModelVersion
from .discovery import get_metadata_path

logger = logging.getLogger(__name__)


class MetadataManager:
    """
    Manager for model metadata.

    This class handles fetching metadata from the CivitAI API and saving it to disk.
    """

    def __init__(self, config: Dict[str, Any], api_client: CivitAIClient):
        """
        Initialize metadata manager.

        Args:
            config: Configuration dictionary
            api_client: CivitAI API client
        """
        self.config = config
        self.api_client = api_client

        # Get output configuration
        self.output_config = config.get("output", {})

    def fetch_metadata(
        self, file_hash: str, force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch metadata from API.

        Args:
            file_hash: File hash
            force_refresh: Whether to force refresh metadata

        Returns:
            Metadata or None if fetching failed
        """
        if not file_hash:
            logger.warning("Cannot fetch metadata without file hash")
            return None

        try:
            logger.debug(f"Fetching metadata for hash {file_hash}")
            response = self.api_client.get_model_version_by_hash(
                file_hash, force_refresh=force_refresh
            )
            if isinstance(response, ModelVersion):
                return response.__dict__
            return response
        except Exception as e:
            logger.error(f"Failed to fetch metadata for hash {file_hash}: {e}")
            return None

    def save_metadata(
        self, file_path: str, metadata: Dict[str, Any], dry_run: bool = False
    ) -> bool:
        """
        Save metadata to disk.

        Args:
            file_path: Path to model file
            metadata: Metadata to save
            dry_run: Whether to simulate saving metadata

        Returns:
            True if saving succeeded, False otherwise
        """
        # Get metadata path
        metadata_path = get_metadata_path(file_path, self.config)

        if dry_run:
            # Simulate saving metadata in dry run mode
            logger.info(f"Dry run: Would save metadata to {metadata_path}")
            return True

        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(metadata_path), exist_ok=True)

            # Save metadata
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.debug(f"Saved metadata to {metadata_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save metadata to {metadata_path}: {e}")
            return False

    def fetch_and_save(
        self, file_path: str, file_hash: str, force_refresh: bool = False, dry_run: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch metadata from API and save it to disk.

        Args:
            file_path: Path to model file
            file_hash: File hash
            force_refresh: Whether to force refresh metadata
            dry_run: Whether to simulate saving metadata

        Returns:
            Metadata or None if fetching or saving failed
        """
        # Fetch metadata
        metadata = self.fetch_metadata(file_hash, force_refresh)
        if not metadata:
            return None

        # Save metadata
        if not self.save_metadata(file_path, metadata, dry_run):
            return None

        return metadata

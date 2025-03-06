"""
Metadata manager for CivitScraper.

This module handles fetching metadata from the CivitAI API and saving it to disk.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, cast

from ..api.client import CivitAIClient
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
            logger.debug(f"Got API response for hash {file_hash}: {type(response)}")

            # Convert response to metadata dict format
            metadata = (
                response
                if isinstance(response, dict)
                else {
                    "id": response.id,
                    "modelId": response.id,
                    "name": response.name,
                    "createdAt": response.created_at.isoformat(),
                    "downloadUrl": response.download_url,
                    "description": response.description,
                    "trainedWords": response.trained_words,
                    "files": [
                        {
                            "name": f.name,
                            "id": f.id,
                            "sizeKb": f.size_kb,
                            "type": f.type,
                            "metadata": f.metadata.__dict__ if f.metadata else None,
                            "pickleScanResult": f.pickle_scan_result,
                            "virusScanResult": f.virus_scan_result,
                            "scannedAt": f.scanned_at.isoformat() if f.scanned_at else None,
                            "primary": f.primary,
                        }
                        for f in response.files
                    ],
                    "images": [
                        {
                            "id": i.id,
                            "url": i.url,
                            "nsfw": i.nsfw,
                            "width": i.width,
                            "height": i.height,
                            "hash": i.hash,
                            "meta": i.meta.__dict__ if i.meta else None,
                        }
                        for i in response.images
                    ],
                    "stats": response.stats.__dict__ if response.stats else None,
                }
            )

            # Validate required fields
            if not metadata.get("images"):
                logger.warning(f"No images found in metadata for hash {file_hash}")
                return None

            # Use cast to help mypy understand the type
            images = cast(List[Any], metadata.get("images", []))
            logger.debug(f"Processed hash: {file_hash}, found {len(images)} images")
            return metadata
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

        # Check if metadata file exists and skip_existing is enabled
        skip_existing = self.config.get("skip_existing", False)
        if skip_existing and os.path.exists(metadata_path):
            logger.info(f"Skipping existing metadata at {metadata_path}")
            return True

        if dry_run:
            # Simulate saving metadata in dry run mode
            logger.info(f"Dry run: Would save metadata to {metadata_path}")
            return True

        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(metadata_path), exist_ok=True)

            # Save metadata - always overwrite if we reached this point
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.debug(f"Saved metadata to {metadata_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save metadata to {metadata_path}: {e}")
            return False

    def load_existing_metadata(self, metadata_path: str) -> Optional[Dict[str, Any]]:
        """
        Load existing metadata from disk.

        Args:
            metadata_path: Path to metadata file

        Returns:
            Metadata dictionary or None if loading failed
        """
        try:
            with open(metadata_path, "r") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                logger.warning(f"Metadata at {metadata_path} is not a dictionary")
                return None

            return data
        except Exception as e:
            logger.error(f"Failed to load existing metadata from {metadata_path}: {e}")
            return None

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
        # Check if metadata file exists and skip_existing is enabled
        skip_existing = self.config.get("skip_existing", False)
        metadata_path = get_metadata_path(file_path, self.config)

        # Try to load existing metadata first if applicable
        if skip_existing and os.path.exists(metadata_path) and not force_refresh:
            logger.info(f"Using existing metadata at {metadata_path}")
            existing_metadata = self.load_existing_metadata(metadata_path)
            if existing_metadata:
                return existing_metadata

        # If we reach this point, we need to fetch new metadata
        metadata = self.fetch_metadata(file_hash, force_refresh)
        if not metadata:
            return None

        # Save metadata
        if not self.save_metadata(file_path, metadata, dry_run):
            return None

        return metadata

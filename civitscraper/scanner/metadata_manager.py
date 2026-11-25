"""
Metadata manager for CivitScraper.

This module handles fetching metadata from the CivitAI API and saving it to disk.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from ..api.client import CivitAIClient
from ..api.domains import get_domain_settings, is_nsfw
from ..api.exceptions import ClientError
from ..utils.cache import DiskCache
from ..utils.fs import atomic_write
from .discovery import get_metadata_path

logger = logging.getLogger(__name__)

# Hashes CivitAI answered 404 for are not looked up again for this long.
NOT_FOUND_CACHE_VALIDITY = 7 * 24 * 60 * 60


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

        _, self.nsfw_threshold, self.nsfw_browsing_level = get_domain_settings(config)
        # Preview count cap for the NSFW image feed (mirrors image download limit).
        self.nsfw_feed_limit = self.output_config.get("images", {}).get("max_count") or 20

        # Negative cache: hashes CivitAI does not know (404). Only a definite 404 is
        # recorded; network errors, 5xx and rate limits are retried next run.
        scanner_config = config.get("scanner", {})
        self.not_found_cache = DiskCache[bool](
            os.path.join(scanner_config.get("cache_dir", ".civitscraper_cache"), "not_found"),
            validity=scanner_config.get("not_found_validity", NOT_FOUND_CACHE_VALIDITY),
        )

    def is_known_not_found(self, file_hash: str) -> bool:
        """Whether CivitAI recently answered 404 for this hash."""
        return self.not_found_cache.get(f"hash_{file_hash}") is True

    def fetch_metadata(
        self, file_hash: str, force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch a model version's metadata by file hash.

        Args:
            file_hash: File hash
            force_refresh: Whether to force refresh metadata

        Returns:
            Metadata, or None when CivitAI does not know the hash (404, remembered
            for ``not_found_validity`` seconds)

        Raises:
            CivitAIError: Network errors, server errors, rate limits and an open circuit
                breaker; they are not remembered, so the next run retries
        """
        if not file_hash:
            logger.warning("Cannot fetch metadata without file hash")
            return None

        if not force_refresh and self.is_known_not_found(file_hash):
            logger.debug(f"Hash {file_hash} was not found on CivitAI recently; skipping lookup")
            return None

        logger.debug(f"Fetching metadata for hash {file_hash}")
        try:
            response = self.api_client.get_model_version_by_hash(
                file_hash, force_refresh=force_refresh
            )
        except ClientError as e:
            if e.status_code == 404:
                self.not_found_cache.set(f"hash_{file_hash}", True)
                logger.info(f"Hash {file_hash} is not known to CivitAI")
                return None
            raise
        if not isinstance(response, dict):
            raise ValueError(f"Unexpected API response for hash {file_hash}: {type(response)}")
        metadata: Dict[str, Any] = response

        # For NSFW models the inline by-hash images are browsing-level
        # filtered (SFW only). Pull the full media set from the images feed
        # with an explicit nsfw browsing level instead.
        if is_nsfw(metadata, self.nsfw_threshold):
            feed_images = self._fetch_nsfw_images(metadata.get("id"), force_refresh)
            if feed_images:
                metadata["images"] = feed_images

        # A model without preview images is still a valid CivitAI match: keep its
        # metadata (otherwise it is treated as "not found" and re-queried forever).
        if not metadata.get("images"):
            logger.info(f"No preview images listed for hash {file_hash}")

        logger.debug(
            f"Processed hash: {file_hash}, found {len(metadata.get('images') or [])} images"
        )
        return metadata

    def _fetch_nsfw_images(
        self, version_id: Optional[int], force_refresh: bool
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch the NSFW image feed for a version and map to inline shape.

        Returns None when the feed could not be fetched (the caller keeps what it
        has) and an empty list when the feed has no images.
        """
        if not version_id:
            return None
        try:
            response = self.api_client.get_images(
                model_version_id=version_id,
                nsfw=self.nsfw_browsing_level,
                limit=self.nsfw_feed_limit,
                force_refresh=force_refresh,
            )
            items = response.get("items", []) if isinstance(response, dict) else []
            mapped: List[Dict[str, Any]] = []
            for item in items:
                level = item.get("nsfwLevel", 0)
                mapped.append(
                    {
                        "id": item.get("id"),
                        "url": item.get("url"),
                        # The level itself, so pages can compare it with the threshold
                        "nsfwLevel": level,
                        "type": item.get("type"),
                        "nsfw": bool(
                            isinstance(level, (int, float)) and level >= self.nsfw_threshold
                        ),
                        "width": item.get("width"),
                        "height": item.get("height"),
                        "hash": item.get("hash"),
                        "meta": item.get("meta"),
                    }
                )
            return mapped
        except Exception as e:
            logger.warning(f"Failed to fetch NSFW image feed for version {version_id}: {e}")
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

        # Consume the transient dirty marker (set by the version enricher when it
        # refreshes siblingVersions). Pop it so it is never serialized to disk.
        dirty = metadata.pop("_civitscraper_dirty", False)

        # Check if metadata file exists and skip_existing is enabled. A dirty
        # (freshly enriched) metadata always writes, so version refreshes reach
        # disk even when skip_existing would otherwise skip the write.
        skip_existing = self.config.get("skip_existing", False)
        if skip_existing and not dirty and os.path.exists(metadata_path):
            logger.debug(f"Skipping existing metadata at {metadata_path}")
            return True

        if dry_run:
            # Simulate saving metadata in dry run mode
            logger.info(f"Dry run: Would save metadata to {metadata_path}")
            return True

        try:
            # Save metadata - always overwrite if we reached this point
            atomic_write(metadata_path, json.dumps(metadata, indent=2))

            logger.debug(f"Saved metadata to {metadata_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save metadata to {metadata_path}: {e}")
            return False

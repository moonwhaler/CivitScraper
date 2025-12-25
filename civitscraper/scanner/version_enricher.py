"""
Version enricher for CivitScraper.

This module enriches version metadata with parent model and sibling version data,
with batch deduplication to minimize API calls.
"""

import logging
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from ..api.client import CivitAIClient
from ..utils.cache import DiskCache

logger = logging.getLogger(__name__)

# Cache validity for failed model IDs (7 days)
FAILED_MODEL_CACHE_VALIDITY = 7 * 24 * 60 * 60


class VersionEnricher:
    """
    Enriches version metadata with parent model and sibling version data.

    This class handles fetching parent model data for multiple files,
    deduplicating API calls when multiple files share the same parent model.
    Failed model lookups (404s for deleted models) are cached to avoid
    repeated failed requests.
    """

    def __init__(self, api_client: CivitAIClient, config: Optional[Dict[str, Any]] = None):
        """
        Initialize version enricher.

        Args:
            api_client: CivitAI API client
            config: Optional configuration dictionary
        """
        self.api_client = api_client
        self.config = config or {}

        # Get cache directory from config or use default
        cache_dir = self.config.get("scanner", {}).get("cache_dir", ".civitscraper_cache")
        failed_models_cache_dir = os.path.join(cache_dir, "failed_models")

        # Disk cache for failed model IDs (persisted across runs)
        self._failed_models_cache = DiskCache[bool](
            failed_models_cache_dir, validity=FAILED_MODEL_CACHE_VALIDITY
        )

        # In-memory set of failed model IDs for current batch
        self._batch_failed_models: Set[int] = set()

    def _is_model_known_failed(self, model_id: int) -> bool:
        """
        Check if a model ID is known to have failed (e.g., 404).

        Args:
            model_id: Model ID to check

        Returns:
            True if model is known to have failed, False otherwise
        """
        # Check in-memory first (current batch)
        if model_id in self._batch_failed_models:
            return True

        # Check disk cache (persisted failures)
        cache_key = f"failed_model_{model_id}"
        return self._failed_models_cache.get(cache_key) is True

    def _mark_model_failed(self, model_id: int):
        """
        Mark a model ID as failed (e.g., 404).

        Args:
            model_id: Model ID to mark as failed
        """
        self._batch_failed_models.add(model_id)
        cache_key = f"failed_model_{model_id}"
        self._failed_models_cache.set(cache_key, True)

    def enrich_batch(
        self,
        metadata_dict: Dict[str, Dict[str, Any]],
        force_refresh: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Enrich a batch of metadata with parent model data.

        Deduplicates API calls by grouping files by modelId, so each unique
        parent model is fetched only once. Failed model lookups (404s) are
        cached to avoid repeated failed requests.

        Args:
            metadata_dict: Dictionary mapping file_path -> metadata
            force_refresh: Force refresh cache for API calls

        Returns:
            Enriched metadata dictionary with parentModel and siblingVersions added
        """
        if not metadata_dict:
            return metadata_dict

        # Clear batch-level failed models cache for new batch
        self._batch_failed_models.clear()

        # Group files by parent model ID, skipping those that already have sibling versions
        files_by_model: Dict[int, List[str]] = defaultdict(list)
        already_enriched = 0

        for file_path, metadata in metadata_dict.items():
            # Skip if already has sibling versions
            if metadata.get("siblingVersions"):
                already_enriched += 1
                continue

            model_id = metadata.get("modelId")
            if model_id:
                files_by_model[model_id].append(file_path)
            else:
                logger.debug(f"No modelId found in metadata for {file_path}")

        unique_models = len(files_by_model)
        files_to_enrich = sum(len(files) for files in files_by_model.values())

        if unique_models == 0:
            if already_enriched > 0:
                logger.info(f"All {already_enriched} files already enriched, skipping")
            return metadata_dict

        logger.info(
            f"Enriching {files_to_enrich} files from {unique_models} unique parent models "
            f"({already_enriched} already enriched)"
        )

        # Count models to skip due to known failures
        models_to_skip = sum(1 for mid in files_by_model if self._is_model_known_failed(mid))
        if models_to_skip > 0:
            logger.info(f"Skipping {models_to_skip} models with known failed lookups (cached 404s)")

        # Fetch each unique parent model once
        parent_model_cache: Dict[int, Dict[str, Any]] = {}
        fetched_count = 0
        failed_count = 0
        skipped_count = 0
        start_time = time.time()

        model_ids = list(files_by_model.keys())
        for idx, model_id in enumerate(model_ids, 1):
            # Skip if known to have failed
            if self._is_model_known_failed(model_id):
                skipped_count += 1
                continue

            # Progress logging every 10 models or at certain milestones
            if idx == 1 or idx % 10 == 0 or idx == len(model_ids):
                elapsed = time.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                remaining = (len(model_ids) - idx) / rate if rate > 0 else 0
                logger.info(
                    f"Fetching parent models: {idx}/{unique_models} "
                    f"({fetched_count} success, {failed_count} failed, {skipped_count} skipped) "
                    f"[{remaining:.0f}s remaining]"  # noqa: E231
                )

            # Get any file's version ID for this model to mark as current
            # We'll update isCurrent per-file when enriching
            parent_data = self.api_client.get_parent_model_with_versions(
                model_id, current_version_id=0, force_refresh=force_refresh
            )

            if parent_data:
                parent_model_cache[model_id] = parent_data
                fetched_count += 1
                logger.debug(
                    f"Fetched parent model {model_id}: "
                    f"{len(parent_data.get('siblingVersions', []))} versions"
                )
            else:
                # Mark as failed for future runs
                self._mark_model_failed(model_id)
                failed_count += 1
                logger.debug(f"Failed to fetch parent model {model_id}, cached as failed")

        # Log final fetch stats
        elapsed = time.time() - start_time
        logger.info(
            f"Finished fetching parent models in {elapsed:.1f}s: "  # noqa: E231
            f"{fetched_count} success, {failed_count} failed, {skipped_count} skipped"
        )

        # Enrich each file's metadata
        enriched_count = 0
        for file_path, metadata in metadata_dict.items():
            # Skip if already has sibling versions
            if metadata.get("siblingVersions"):
                continue

            model_id = metadata.get("modelId")
            if not model_id or model_id not in parent_model_cache:
                continue

            parent_data = parent_model_cache[model_id]
            version_id = metadata.get("id")

            # Copy parent model info
            metadata["parentModel"] = parent_data["parentModel"]

            # Copy sibling versions and update isCurrent flag for this file
            sibling_versions = []
            for version in parent_data.get("siblingVersions", []):
                version_copy = version.copy()
                version_copy["isCurrent"] = version.get("id") == version_id
                sibling_versions.append(version_copy)

            metadata["siblingVersions"] = sibling_versions
            enriched_count += 1

        logger.info(
            f"Enriched {enriched_count}/{files_to_enrich} files with parent model data "
            f"({fetched_count} API calls made)"
        )

        return metadata_dict

    def enrich_single(
        self,
        metadata: Dict[str, Any],
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Enrich a single metadata dict with parent model data.

        Args:
            metadata: Metadata dictionary to enrich
            force_refresh: Force refresh cache

        Returns:
            Enriched metadata dictionary
        """
        # Skip if already has sibling versions
        if metadata.get("siblingVersions"):
            logger.debug("Metadata already has siblingVersions, skipping enrichment")
            return metadata

        model_id = metadata.get("modelId")
        version_id = metadata.get("id")

        if not model_id:
            logger.debug("No modelId in metadata, skipping enrichment")
            return metadata

        # Skip if known to have failed
        if self._is_model_known_failed(model_id):
            logger.debug(f"Skipping model {model_id}, known failed lookup")
            return metadata

        parent_data = self.api_client.get_parent_model_with_versions(
            model_id, current_version_id=version_id or 0, force_refresh=force_refresh
        )

        if parent_data:
            metadata["parentModel"] = parent_data["parentModel"]
            metadata["siblingVersions"] = parent_data["siblingVersions"]
            logger.debug(
                f"Enriched metadata with {len(parent_data.get('siblingVersions', []))} "
                f"sibling versions"
            )
        else:
            self._mark_model_failed(model_id)
            logger.debug(f"Failed to fetch parent model {model_id}, cached as failed")

        return metadata

    def clear_failed_cache(self):
        """Clear the cache of failed model lookups."""
        self._batch_failed_models.clear()
        self._failed_models_cache.clear()
        logger.info("Cleared failed model lookup cache")

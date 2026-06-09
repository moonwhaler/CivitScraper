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

# Default validity for cached sibling/remote version lists (24 hours)
SIBLING_VERSIONS_CACHE_VALIDITY_DEFAULT = 86400
# Field stamped into sidecar metadata recording when siblingVersions was fetched
SIBLING_VERSIONS_TS_FIELD = "siblingVersionsFetchedAt"
# Transient in-memory marker telling save_metadata to bypass skip_existing.
# Popped before serialization; never written to disk.
DIRTY_FLAG = "_civitscraper_dirty"


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

        # TTL for cached sibling/remote version lists. Falls back to the general
        # scanner cache validity, then a 24h default.
        scanner_cfg = self.config.get("scanner", {})
        self._version_ttl = scanner_cfg.get(
            "version_cache_validity",
            scanner_cfg.get("cache_validity", SIBLING_VERSIONS_CACHE_VALIDITY_DEFAULT),
        )

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

    def _siblings_expired(self, metadata: Dict[str, Any]) -> bool:
        """
        Return True if metadata has siblingVersions but they are stale.

        Stale means the fetch timestamp is missing (legacy sidecar) or older than
        the configured TTL. Returns False when there are no siblingVersions at all
        (that case is "never enriched", not "expired").
        """
        if not metadata.get("siblingVersions"):
            return False
        ts = metadata.get(SIBLING_VERSIONS_TS_FIELD)
        if not isinstance(ts, (int, float)):
            return True
        if self._version_ttl <= 0:
            return True
        return (time.time() - ts) >= self._version_ttl

    def needs_enrichment(self, metadata: Dict[str, Any], force_refresh: bool = False) -> bool:
        """
        Return True if a file's sibling version data should be (re)fetched.

        True when force_refresh is set, when siblingVersions has never been
        fetched, or when the existing siblingVersions has gone stale (TTL).
        """
        if force_refresh:
            return True
        if not metadata.get("siblingVersions"):
            return True
        return self._siblings_expired(metadata)

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

        # Group files by parent model ID, skipping those whose sibling versions are
        # still fresh. force_models accumulates (as a union across all files sharing
        # a model) the models whose siblings are present-but-stale, so the
        # deduplicated fetch bypasses the HTTP request cache for those.
        files_by_model: Dict[int, List[str]] = defaultdict(list)
        force_models: Set[int] = set()
        already_enriched = 0

        for file_path, metadata in metadata_dict.items():
            # Skip if sibling versions are still fresh
            if not self.needs_enrichment(metadata, force_refresh):
                already_enriched += 1
                continue

            model_id = metadata.get("modelId")
            if model_id:
                files_by_model[model_id].append(file_path)
                if force_refresh or self._siblings_expired(metadata):
                    force_models.add(model_id)
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

        # Fetch parent models in parallel for better performance
        parent_model_cache: Dict[int, Dict[str, Any]] = {}
        fetched_count = 0
        failed_count = 0
        skipped_count = 0
        start_time = time.time()

        # Filter out known failed models
        model_ids_to_fetch = [
            mid for mid in files_by_model.keys() if not self._is_model_known_failed(mid)
        ]
        skipped_count = len(files_by_model) - len(model_ids_to_fetch)

        if skipped_count > 0:
            logger.info(f"Skipping {skipped_count} models with known failed lookups")

        # Use concurrent fetching for better performance
        import concurrent.futures

        max_workers = min(8, len(model_ids_to_fetch)) if model_ids_to_fetch else 1

        def fetch_parent_model(model_id: int) -> tuple:
            """Fetch a single parent model and return (model_id, data or None)."""
            parent_data = self.api_client.get_parent_model_with_versions(
                model_id, current_version_id=0, force_refresh=(model_id in force_models)
            )
            return (model_id, parent_data)

        if model_ids_to_fetch:
            logger.info(
                f"Fetching {len(model_ids_to_fetch)} parent models "
                f"with {max_workers} concurrent workers"
            )

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_model = {
                    executor.submit(fetch_parent_model, mid): mid for mid in model_ids_to_fetch
                }

                completed = 0
                for future in concurrent.futures.as_completed(future_to_model):
                    completed += 1
                    model_id, parent_data = future.result()

                    if parent_data:
                        parent_model_cache[model_id] = parent_data
                        fetched_count += 1
                        logger.debug(
                            f"Fetched parent model {model_id}: "
                            f"{len(parent_data.get('siblingVersions', []))} versions"
                        )
                    else:
                        self._mark_model_failed(model_id)
                        failed_count += 1
                        logger.debug(f"Failed to fetch parent model {model_id}, cached as failed")

                    # Progress logging every 10 completions
                    if completed % 10 == 0 or completed == len(model_ids_to_fetch):
                        elapsed = time.time() - start_time
                        rate = completed / elapsed if elapsed > 0 else 0
                        remaining = (len(model_ids_to_fetch) - completed) / rate if rate > 0 else 0
                        logger.info(
                            f"Fetching parent models: {completed}/{len(model_ids_to_fetch)} "
                            f"({fetched_count} success, {failed_count} failed) "
                            f"[{remaining:.0f}s remaining]"  # noqa: E231
                        )

        # Log final fetch stats
        elapsed = time.time() - start_time
        logger.info(
            f"Finished fetching parent models in {elapsed:.1f}s: "  # noqa: E231
            f"{fetched_count} success, {failed_count} failed, {skipped_count} skipped"
        )

        # Enrich each file's metadata
        enriched_count = 0
        for file_path, metadata in metadata_dict.items():
            # Skip if sibling versions are still fresh
            if not self.needs_enrichment(metadata, force_refresh):
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
            # Stamp fetch time and mark dirty so save_metadata persists the
            # refresh even when skip_existing would otherwise skip the write.
            metadata[SIBLING_VERSIONS_TS_FIELD] = time.time()
            metadata[DIRTY_FLAG] = True
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
        # Skip if sibling versions are still fresh
        if not self.needs_enrichment(metadata, force_refresh):
            logger.debug("Metadata already has fresh siblingVersions, skipping enrichment")
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

        # Stale-but-present siblings must bypass the HTTP request cache.
        force_fetch = force_refresh or self._siblings_expired(metadata)
        parent_data = self.api_client.get_parent_model_with_versions(
            model_id, current_version_id=version_id or 0, force_refresh=force_fetch
        )

        if parent_data:
            metadata["parentModel"] = parent_data["parentModel"]
            metadata["siblingVersions"] = parent_data["siblingVersions"]
            metadata[SIBLING_VERSIONS_TS_FIELD] = time.time()
            metadata[DIRTY_FLAG] = True
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

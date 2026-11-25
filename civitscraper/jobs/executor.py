"""
Job executor for CivitScraper.

This module handles executing jobs defined in the configuration.
"""

import concurrent.futures
import json
import logging
import os
import shutil
import threading
from typing import Any, Dict, List, Optional, Tuple

from ..api.client import CivitAIClient
from ..config.loader import merge_configs
from ..html.generator import HTMLGenerator
from ..organization import FileOrganizer, OrganizationConfig
from ..organization.organizer import is_in_organized_output
from ..scanner.discovery import filter_files, find_model_files, get_metadata_path
from ..scanner.processor import ModelProcessor
from ..utils.fs import atomic_write

logger = logging.getLogger(__name__)


class JobExecutor:
    """Executor for jobs."""

    def __init__(self, config: Dict[str, Any], api_client: CivitAIClient):
        """
        Initialize job executor.

        Args:
            config: Configuration
            api_client: CivitAI API client
        """
        self.config = config
        self.api_client = api_client

    def execute_job(self, job_name: str) -> bool:
        """
        Execute a job.

        Args:
            job_name: Job name

        Returns:
            True if job was executed successfully, False otherwise
        """
        # Get job configuration
        job_config = self.config.get("jobs", {}).get(job_name)
        if not job_config:
            logger.error(f"Job not found: {job_name}")
            return False

        # Log the job configuration for debugging
        logger.debug(f"Job configuration for {job_name}: {job_config}")

        # Get job type
        job_type = job_config.get("type")
        if not job_type:
            logger.error(f"No job type specified for job: {job_name}")
            return False

        # Execute job based on type
        if job_type == "scan-paths":
            return self._execute_scan_paths_job(job_name, job_config)
        elif job_type == "sync-lora-triggers":
            return self._execute_sync_lora_triggers_job(job_name, job_config)
        else:
            logger.error(f"Unknown job type: {job_type}")
            return False

    def execute_all_jobs(self) -> Dict[str, bool]:
        """
        Execute all jobs.

        Returns:
            Dictionary of job name -> success
        """
        # Get jobs
        jobs = self.config.get("jobs", {})

        # Execute jobs
        results = {}

        for job_name in jobs:
            logger.info(f"Executing job: {job_name}")
            success = self.execute_job(job_name)
            results[job_name] = success

            if success:
                logger.info(f"Job {job_name} executed successfully")
            else:
                logger.error(f"Job {job_name} failed")

        return results

    def _build_job_config(self, job_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge a job's settings over the global configuration.

        Dict values are merged recursively; other values override.

        Args:
            job_config: Job configuration

        Returns:
            Job-specific configuration
        """
        job_specific_config = self.config.copy()
        for key, value in job_config.items():
            if (
                key in job_specific_config
                and isinstance(job_specific_config[key], dict)
                and isinstance(value, dict)
            ):
                job_specific_config[key] = merge_configs(job_specific_config[key], value)
            else:
                job_specific_config[key] = value
        return job_specific_config

    def _execute_scan_paths_job(self, job_name: str, job_config: Dict[str, Any]) -> bool:
        """
        Execute a scan-paths job.

        Args:
            job_name: Job name
            job_config: Job configuration

        Returns:
            True if job was executed successfully, False otherwise
        """
        try:
            # Get paths
            path_ids = job_config.get("paths", [])
            if not path_ids:
                # If no paths specified, use all LORA paths
                path_ids = [
                    path_id
                    for path_id, path_config in self.config.get("input_paths", {}).items()
                    if path_config.get("type") == "LORA"
                ]
                if not path_ids:
                    logger.error(
                        f"No paths specified for job: {job_name} "
                        f"and no LORA paths found in configuration"
                    )
                    return False
                logger.info(f"No paths specified, using all LORA paths: {path_ids}")

            # Get scan options
            skip_existing = job_config.get("skip_existing", True)
            verify_hashes = job_config.get("verify_hashes", True)
            if not verify_hashes and not job_config.get("use_cached_metadata", False):
                # CivitAI lookups are by file hash; without one every file would fail.
                logger.warning(
                    "verify_hashes: false is ignored for API lookups (the file hash is "
                    "how models are identified on CivitAI)"
                )
                verify_hashes = True
            use_cached_metadata = job_config.get("use_cached_metadata", False)

            # Find model files
            logger.info(f"Finding model files for paths: {path_ids}")
            # Use job's recursive setting if specified
            job_recursive = job_config.get("recursive")
            path_files = find_model_files(self.config, path_ids, job_recursive)

            # Flatten files
            files: List[str] = []
            for path_id, path_files_list in path_files.items():
                files.extend(path_files_list)

            job_specific_config = self._build_job_config(job_config)

            # Copies/symlinks in the organization output mirror originals that are
            # scanned anyway; rescanning them duplicates hashing and gallery cards
            # (and recursive scans would organize the copies again). Moved files are
            # the only copy, so they stay in the scan and the organizer leaves them
            # in place.
            org_settings = OrganizationConfig.from_dict(job_specific_config)
            mirror_mode = org_settings.enabled and org_settings.operation_mode in (
                "copy",
                "symlink",
            )
            if mirror_mode:
                before = len(files)
                files = [
                    f
                    for f in files
                    if not is_in_organized_output(f, org_settings, job_specific_config)
                ]
                if len(files) != before:
                    logger.info(
                        f"Ignoring {before - len(files)} {org_settings.operation_mode} "
                        f"files inside the organization output"
                    )

            # Filter files based on mode
            logger.info(f"Found {len(files)} files, filtering...")
            if use_cached_metadata:
                # Only include files that HAVE existing metadata
                filtered_files = [
                    f for f in files if self._has_cached_metadata(f, job_specific_config)
                ]
                logger.info(f"Found {len(filtered_files)} files with cached metadata")
            else:
                filtered_files = filter_files(files, skip_existing, job_specific_config)
                logger.info(f"Filtered to {len(filtered_files)} files")

            # Create a temporary HTML generator with job-specific configuration
            # This ensures the gallery_path and other job settings are used
            temp_html_generator = HTMLGenerator(job_specific_config)

            # Create a temporary processor with the job-specific configuration
            temp_processor = ModelProcessor(
                job_specific_config, self.api_client, temp_html_generator
            )

            # Get force_refresh setting from job-specific scanner configuration
            force_refresh = job_config.get("force_refresh", False)
            if not force_refresh:
                force_refresh = job_specific_config.get("scanner", {}).get("force_refresh", False)

            # PHASE 1: Fetch metadata
            logger.info(f"Fetching metadata for {len(filtered_files)} files")
            metadata_dict = {}
            organized_files_mapping = {}

            summary = {
                "not_found": 0,
                "not_found_cached": 0,
                "unreadable": 0,
                "errors": 0,
                "output_failed": 0,
            }

            # Hash + look up files in parallel. Hashing releases the GIL (hashlib), and
            # API calls are additionally bounded by api.batch.max_concurrent; the shared
            # rate limiter, circuit breaker and caches are thread-safe.
            batch_config = job_specific_config.get("api", {}).get("batch", {})
            parallel = batch_config.get("enabled", True)
            workers = (
                max(1, int(job_specific_config.get("scanner", {}).get("hash_workers", 4)))
                if parallel
                else 1
            )
            api_slots = threading.BoundedSemaphore(
                max(1, int(batch_config.get("max_concurrent", 4))) if parallel else 1
            )

            def fetch_one(file_path: str) -> Tuple[str, Optional[Dict[str, Any]]]:
                """Return (outcome, metadata) for one file."""
                try:
                    if use_cached_metadata:
                        metadata = self._load_cached_metadata(file_path, job_specific_config)
                        if metadata:
                            logger.debug(f"Loaded cached metadata for {file_path}")
                            return "matched", metadata
                        logger.warning(f"No cached metadata found for {file_path}")
                        return "not_found", None

                    result = temp_processor.file_processor.process(
                        file_path, verify_hash=verify_hashes
                    )
                    if not result.success or not result.file_hash:
                        logger.warning(f"Failed to process file {file_path}: {result.error}")
                        return "unreadable", None

                    if not force_refresh and temp_processor.metadata_manager.is_known_not_found(
                        result.file_hash
                    ):
                        return "not_found_cached", None

                    with api_slots:
                        metadata = temp_processor.metadata_manager.fetch_metadata(
                            result.file_hash, force_refresh=force_refresh
                        )
                    if metadata:
                        logger.debug(f"Got metadata for {file_path}")
                        return "matched", metadata
                    logger.warning(f"No metadata found for {file_path}")
                    return "not_found", None
                except Exception as e:
                    logger.error(f"Error fetching metadata for {file_path}: {e}")
                    logger.debug("Traceback:", exc_info=True)
                    return "errors", None

            fetched: Dict[str, Dict[str, Any]] = {}
            if workers > 1 and len(filtered_files) > 1:
                logger.info(f"Hashing and looking up with {workers} workers")
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(fetch_one, f): f for f in filtered_files}
                    for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
                        outcome, metadata = future.result()
                        if metadata is not None:
                            fetched[futures[future]] = metadata
                        else:
                            summary[outcome] += 1
                        if done % 100 == 0 or done == len(filtered_files):
                            logger.info(f"Looked up {done}/{len(filtered_files)} files")
            else:
                for file_path in filtered_files:
                    outcome, metadata = fetch_one(file_path)
                    if metadata is not None:
                        fetched[file_path] = metadata
                    else:
                        summary[outcome] += 1

            # Keep discovery order so later phases behave deterministically.
            for file_path in filtered_files:
                if file_path in fetched:
                    metadata_dict[file_path] = fetched[file_path]

            temp_processor.file_processor.flush()

            # PHASE 1.5: Enrich with parent model data (deduplicated by modelId).
            # Run enrichment if any file's sibling versions are missing or stale
            # (TTL). Skipped entirely for offline cached-metadata jobs
            # (e.g. regenerate-html), which must not hit the API.
            if metadata_dict and not use_cached_metadata:
                from ..scanner.version_enricher import VersionEnricher

                enricher = VersionEnricher(self.api_client, job_specific_config)
                if any(
                    enricher.needs_enrichment(meta, force_refresh)
                    for meta in metadata_dict.values()
                ):
                    logger.info(f"Enriching {len(metadata_dict)} files with parent model data")
                    metadata_dict = enricher.enrich_batch(
                        metadata_dict, force_refresh=force_refresh
                    )

            # PHASE 2: Calculate target paths if organization is enabled
            organization_config = job_config.get("organization", {})
            if organization_config.get("enabled", False) and metadata_dict:
                logger.info(f"Calculating target paths for {len(metadata_dict)} files")
                logger.debug(f"Using organization settings from job: {organization_config}")

                # Create a job-specific organizer with the updated configuration
                job_organizer = FileOrganizer(job_specific_config)

                # Organize pre-existing files
                logger.info(f"Organizing {len(metadata_dict)} files")
                organized_results = job_organizer.organize_files(
                    list(metadata_dict.keys()), metadata_dict
                )

                # Create mapping from original path to new path
                for orig_path, new_path in organized_results:
                    if new_path:
                        organized_files_mapping[orig_path] = new_path

            # Images are downloaded per model in phase 4b (in parallel, right before
            # that model's HTML is rendered), into the organized location if any.
            if metadata_dict and not job_specific_config.get("output", {}).get("images", {}).get(
                "save", True
            ):
                logger.info("Skipping image downloads (images.save is false)")

            # PHASE 4: Process remaining tasks (metadata, HTML) with parallelization
            logger.info(f"Processing {len(metadata_dict)} files with metadata")
            results = []

            # Prepare items for processing
            items_to_process = []
            originals_needing_sidecar = []
            for file_path, metadata in metadata_dict.items():
                process_path = organized_files_mapping.get(file_path, file_path) or file_path
                items_to_process.append((process_path, metadata))
                if mirror_mode and process_path != file_path:
                    originals_needing_sidecar.append((file_path, metadata))

            # PHASE 4a: Flush every sidecar to disk first (using the resolved,
            # possibly-organized process_path), then rebuild the version index against
            # the complete sidecar set. This makes the per-model version union on each
            # detail page deterministic regardless of HTML generation order in 4b.
            from ..html.context import _version_index_cache, invalidate_version_index

            # Copy/symlink mode: the original stays where it is and is what the next
            # scan finds, so it needs its own sidecar or skip_existing never skips it.
            # Written first (on a copy carrying the enricher's dirty flag) because
            # save_metadata consumes that flag.
            for original_path, metadata in originals_needing_sidecar:
                temp_processor.metadata_manager.save_metadata(
                    original_path, dict(metadata), temp_processor.dry_run
                )

            for process_path, metadata in items_to_process:
                temp_processor.metadata_manager.save_metadata(
                    process_path, metadata, temp_processor.dry_run
                )

            invalidate_version_index()
            if not temp_processor.dry_run:
                index_dirs = {
                    os.path.dirname(os.path.abspath(get_metadata_path(p, job_specific_config)))
                    for p, _ in items_to_process
                }
                for index_dir in index_dirs:
                    _version_index_cache.ensure_indexed(index_dir)

            # PHASE 4b: Generate images + HTML. The internal save_metadata is now a
            # no-op for already-written sidecars (dirty flag consumed in 4a).
            # Use parallel processing for large collections
            if len(items_to_process) > 10:
                download_workers = (
                    job_specific_config.get("api", {}).get("batch", {}).get("download_workers", 4)
                )
                max_workers = max(1, min(int(download_workers), len(items_to_process)))
                logger.info(f"Processing {len(items_to_process)} files with {max_workers} workers")

                def process_single_item(
                    item: Tuple[str, Dict[str, Any]],
                ) -> Tuple[str, Optional[Dict[str, Any]]]:
                    path, meta = item
                    processed = temp_processor.save_and_process_with_metadata(
                        path, meta, force_refresh=force_refresh
                    )
                    return (path, processed)

                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_item = {
                        executor.submit(process_single_item, item): item
                        for item in items_to_process
                    }
                    completed = 0
                    for future in concurrent.futures.as_completed(future_to_item):
                        completed += 1
                        try:
                            item_result = future.result()
                            results.append(item_result)
                        except Exception as e:
                            item = future_to_item[future]
                            logger.error(f"Error processing {item[0]}: {e}")
                            results.append((item[0], None))

                        # Progress logging every 50 files
                        if completed % 50 == 0 or completed == len(items_to_process):
                            logger.info(f"Processed {completed}/{len(items_to_process)} files")
            else:
                # Sequential processing for small collections
                for process_path, metadata in items_to_process:
                    processed_metadata = temp_processor.save_and_process_with_metadata(
                        process_path, metadata, force_refresh=force_refresh
                    )
                    results.append((process_path, processed_metadata))

            # PHASE 4: Generate gallery
            html_config = job_config.get("output", {}).get("metadata", {}).get("html", {})
            if html_config.get("generate_gallery", False):
                gallery_path = html_config.get("gallery_path", "gallery.html")
                gallery_title = html_config.get("gallery_title", "Model Gallery")
                include_existing = html_config.get("include_existing_in_gallery", True)

                logger.info(f"Generating gallery at {gallery_path}")
                logger.debug(f"Include existing model cards: {include_existing}")

                # Store the path_ids in the config for use by find_html_files
                if include_existing:
                    job_specific_config["gallery_path_ids"] = path_ids

                # Reuse the temp_html_generator already created with job_specific_config
                temp_html_generator.generate_gallery(
                    list(metadata_dict.keys()),
                    gallery_path,
                    gallery_title,
                    include_existing=include_existing,
                )

            summary["output_failed"] = sum(1 for _, meta in results if meta is None)
            logger.info(
                f"Job {job_name} summary: {len(files)} found, "
                f"{len(files) - len(filtered_files)} skipped (already have metadata), "
                f"{len(metadata_dict)} matched, {summary['not_found']} not found on CivitAI "
                f"(+{summary['not_found_cached']} known unknown, not re-queried), "
                f"{summary['unreadable']} unreadable, {summary['errors']} lookup errors, "
                f"{summary['output_failed']} failed while writing output"
            )
            return True

        except Exception as e:
            logger.error(f"Error executing scan-paths job {job_name}: {e}")
            logger.debug("Traceback:", exc_info=True)
            return False

    def _execute_sync_lora_triggers_job(self, job_name: str, job_config: Dict[str, Any]) -> bool:
        """
        Execute a sync-lora-triggers job.

        Args:
            job_name: Job name
            job_config: Job configuration

        Returns:
            True if job was executed successfully, False otherwise
        """
        try:
            # Get paths
            path_ids = job_config.get("paths", [])
            if not path_ids:
                logger.error(f"No paths specified for job: {job_name}")
                return False

            # Get loras.json path
            loras_file = job_config.get("loras_file", "loras.json")
            if not loras_file:
                logger.error(f"No loras_file specified for job: {job_name}")
                return False

            # Get overwrite_triggers setting, default to True if not specified
            overwrite_triggers = job_config.get("overwrite_triggers", True)
            logger.info(f"Overwrite existing triggers: {overwrite_triggers}")

            # Find model files
            logger.info(f"Finding model files for paths: {path_ids}")
            # Use job's recursive setting if specified
            job_recursive = job_config.get("recursive")
            path_files = find_model_files(self.config, path_ids, job_recursive)

            # Flatten files
            files: List[str] = []
            for path_id, path_files_list in path_files.items():
                files.extend(path_files_list)

            # Locate metadata with the same rules as scan jobs (output.base_dir,
            # output.metadata.path/filename from the global config or this job),
            # falling back to the legacy <model>.json next to the model file.
            job_specific_config = self._build_job_config(job_config)
            lora_files: List[Tuple[str, str]] = []
            for file_path in files:
                metadata_path = self._find_metadata_file(file_path, job_specific_config)
                if metadata_path:
                    lora_files.append((file_path, metadata_path))

            # Check if loras.json exists
            if not os.path.isfile(loras_file):
                logger.error(f"loras.json not found at {loras_file}")
                return False

            # Load loras.json
            with open(loras_file, "r") as f:
                loras_data = json.load(f)

            # Update loras.json
            updated_count = 0
            processed_count = 0
            skipped_count = 0
            logger.debug(f"Total files to process: {len(lora_files)}")

            for file_path, metadata_path in lora_files:
                processed_count += 1
                logger.debug(f"Processing {file_path}")

                # Load metadata
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)

                # Try both possible keys for trigger words
                trigger_words = metadata.get("trainedWords")
                if not trigger_words:
                    # Try alternate key if trainedWords not found
                    trigger_words = metadata.get("activation text")
                    if trigger_words:
                        logger.debug(f"Found activation text: {trigger_words}")
                    else:
                        logger.debug(
                            f"No trigger words in trainedWords or activation text for {file_path}"
                        )
                        continue
                else:
                    logger.debug(f"Found trainedWords: {trigger_words}")

                # Get filename for matching
                filename = os.path.basename(file_path)
                logger.debug(f"Looking for entry with filename: {filename}")

                # Find entry in loras.json
                for entry in loras_data:
                    entry_filename = os.path.basename(entry.get("id", ""))
                    if entry_filename == filename:
                        logger.debug(f"Found entry with id: {entry.get('id')}")

                        # Check if we should skip updating
                        if not overwrite_triggers:
                            current_triggers = entry.get("metadata", {}).get("lora_triggers")
                            if current_triggers:
                                logger.debug(
                                    f"Skipping update for {filename} as it already has triggers: "
                                    f"{current_triggers}"
                                )
                                skipped_count += 1
                                break  # Skip to the next file

                        logger.debug(f"Updating with new triggers: {trigger_words}")

                        # Update entry
                        if "metadata" not in entry:
                            entry["metadata"] = {}

                        # Convert trigger_words to a single string if it's a list
                        if isinstance(trigger_words, list):
                            # Join with commas and clean up trailing commas
                            trigger_string = ", ".join(
                                str(word).strip().rstrip(",") for word in trigger_words if word
                            )
                            trigger_string = trigger_string.strip().rstrip(",")
                        else:
                            trigger_string = str(trigger_words).strip()

                        entry["metadata"]["lora_triggers"] = trigger_string
                        updated_count += 1
                        break
                else:
                    logger.debug(f"No matching entry found in loras.json for {filename}")

            # Save loras.json (Krita's own file): never in dry run, keep one backup of
            # the previous version, and write atomically so a crash can't truncate it.
            if self.config.get("dry_run", False) or job_config.get("dry_run", False):
                logger.info(f"Dry run: Would update {updated_count} entries in {loras_file}")
            elif updated_count:
                shutil.copy2(loras_file, loras_file + ".bak")
                atomic_write(loras_file, json.dumps(loras_data, indent=2))
            else:
                logger.info(f"No trigger changes; {loras_file} left untouched")

            logger.info(f"Files processed: {processed_count}")
            logger.info(f"Updated {updated_count} entries in loras.json")
            if not overwrite_triggers:
                logger.info(f"Skipped {skipped_count} entries with existing triggers")

            return True

        except Exception as e:
            logger.error(f"Error executing sync-lora-triggers job {job_name}: {e}")
            logger.debug("Traceback:", exc_info=True)
            return False

    def _find_metadata_file(self, file_path: str, config: Dict[str, Any]) -> Optional[str]:
        """
        Find the metadata file for a model, honoring configured output locations.

        Args:
            file_path: Path to model file
            config: Configuration used to locate the metadata file

        Returns:
            Path to an existing metadata file, or None
        """
        candidates = [
            get_metadata_path(file_path, config),
            os.path.splitext(file_path)[0] + ".json",
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None

    def _has_cached_metadata(self, file_path: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Check if a model file has cached metadata.

        Args:
            file_path: Path to model file
            config: Configuration used to locate the metadata file (defaults to global)

        Returns:
            True if metadata file exists, False otherwise
        """
        metadata_path = get_metadata_path(file_path, config or self.config)
        return os.path.isfile(metadata_path)

    def _load_cached_metadata(
        self, file_path: str, config: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Load cached metadata from JSON file.

        Args:
            file_path: Path to model file
            config: Configuration used to locate the metadata file (defaults to global)

        Returns:
            Metadata dictionary or None if not found
        """
        metadata_path = get_metadata_path(file_path, config or self.config)
        if not os.path.isfile(metadata_path):
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
                return data
        except Exception as e:
            logger.error(f"Error loading cached metadata from {metadata_path}: {e}")
            return None

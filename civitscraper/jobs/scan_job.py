"""
scan-paths job for CivitScraper.

Finds model files, looks them up on CivitAI by hash, enriches them with their
sibling versions, optionally organizes them, and writes sidecars, previews,
detail pages and the gallery.
"""

import concurrent.futures
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from ..api.client import CivitAIClient
from ..config.loader import merge_configs
from ..html.gallery_data import UNMATCHED_NO_METADATA, UNMATCHED_NOT_ON_CIVITAI
from ..html.generator import HTMLGenerator
from ..html.paths import DEFAULT_GALLERY_PATH
from ..organization import FileOrganizer, OrganizationConfig
from ..organization.organizer import is_in_organized_output
from ..scanner.discovery import (
    filter_files,
    find_model_files,
    get_metadata_path,
    has_metadata,
    load_cached_metadata,
)
from ..scanner.processor import ModelProcessor

logger = logging.getLogger(__name__)


class ScanJob:
    """One run of a scan-paths job."""

    def __init__(
        self,
        config: Dict[str, Any],
        job_name: str,
        job_config: Dict[str, Any],
        api_client: CivitAIClient,
    ):
        """
        Prepare a scan-paths job.

        Args:
            config: Global configuration
            job_name: Job name (for log messages)
            job_config: The job's own configuration section
            api_client: CivitAI API client
        """
        self.config = config
        self.job_name = job_name
        self.job_config = job_config
        self.api_client = api_client

        self.path_ids: List[str] = []
        self.files: List[str] = []
        self.filtered_files: List[str] = []
        self.metadata_dict: Dict[str, Dict[str, Any]] = {}
        self.organized_files_mapping: Dict[str, str] = {}
        self.items_to_process: List[Tuple[str, Dict[str, Any]]] = []
        self.results: List[Tuple[str, Optional[Dict[str, Any]]]] = []
        self.mirror_mode = False
        self.summary = {
            "not_found": 0,
            "not_found_cached": 0,
            "unreadable": 0,
            "errors": 0,
            "output_failed": 0,
        }

    def run(self) -> bool:
        """
        Run every phase of the job.

        Returns:
            True if the job was executed successfully, False otherwise
        """
        try:
            if not self.discover():
                return False
            self.fetch()
            self.enrich()
            self.organize()
            self.write_sidecars()
            self.render()
            self.build_gallery()
            self.log_summary()
            return True

        except Exception as e:
            logger.error(f"Error executing scan-paths job {self.job_name}: {e}")
            logger.debug("Traceback:", exc_info=True)
            return False

    # --- Phase 0: discovery -------------------------------------------------

    def discover(self) -> bool:
        """
        Find and filter the job's model files and build its configuration.

        Returns:
            False if the job has no paths to scan
        """
        job_config = self.job_config

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
                    f"No paths specified for job: {self.job_name} "
                    f"and no LORA paths found in configuration"
                )
                return False
            logger.info(f"No paths specified, using all LORA paths: {path_ids}")
        self.path_ids = path_ids

        # Get scan options
        self.skip_existing = bool(job_config.get("skip_existing", True))
        verify_hashes = job_config.get("verify_hashes", True)
        if not verify_hashes and not job_config.get("use_cached_metadata", False):
            # CivitAI lookups are by file hash; without one every file would fail.
            logger.warning(
                "verify_hashes: false is ignored for API lookups (the file hash is "
                "how models are identified on CivitAI)"
            )
            verify_hashes = True
        self.verify_hashes = verify_hashes
        self.use_cached_metadata = job_config.get("use_cached_metadata", False)

        logger.info(f"Finding model files for paths: {path_ids}")
        path_files = find_model_files(self.config, path_ids, job_config.get("recursive"))
        # Nested input paths (e.g. a Lora folder and one of its subfolders) list the
        # same file twice; keep it once so it is hashed and processed once.
        files: List[str] = []
        seen = set()
        for path_files_list in path_files.values():
            for file_path in path_files_list:
                key = os.path.normcase(os.path.abspath(file_path))
                if key not in seen:
                    seen.add(key)
                    files.append(file_path)

        self.job_specific_config = merge_configs(self.config, job_config)
        # One meaning everywhere: the metadata and image managers read this key too,
        # and an unset key must not make them overwrite sidecars and re-download
        # every preview while the scan itself skips existing files.
        self.job_specific_config["skip_existing"] = self.skip_existing

        # Copies/symlinks in the organization output mirror originals that are
        # scanned anyway; rescanning them duplicates hashing and gallery cards
        # (and recursive scans would organize the copies again). Moved files are
        # the only copy, so they stay in the scan and the organizer leaves them
        # in place.
        org_settings = OrganizationConfig.from_dict(self.job_specific_config)
        self.mirror_mode = org_settings.enabled and org_settings.operation_mode in (
            "copy",
            "symlink",
        )
        if self.mirror_mode:
            before = len(files)
            files = [
                f
                for f in files
                if not is_in_organized_output(f, org_settings, self.job_specific_config)
            ]
            if len(files) != before:
                logger.info(
                    f"Ignoring {before - len(files)} {org_settings.operation_mode} "
                    f"files inside the organization output"
                )
        self.files = files

        logger.info(f"Found {len(files)} files, filtering...")
        if self.use_cached_metadata:
            # Only include files that HAVE existing metadata
            self.filtered_files = [f for f in files if has_metadata(f, self.job_specific_config)]
            logger.info(f"Found {len(self.filtered_files)} files with cached metadata")
        else:
            self.filtered_files = filter_files(files, self.skip_existing, self.job_specific_config)
            logger.info(f"Filtered to {len(self.filtered_files)} files")

        # Job-specific generator and processor, so gallery_path and the other job
        # settings are used.
        self.html_generator = HTMLGenerator(self.job_specific_config)
        self.processor = ModelProcessor(
            self.job_specific_config, self.api_client, self.html_generator
        )

        force_refresh = job_config.get("force_refresh", False)
        if not force_refresh:
            force_refresh = self.job_specific_config.get("scanner", {}).get("force_refresh", False)
        self.force_refresh = force_refresh
        return True

    # --- Phase 1: hash + look up ----------------------------------------------

    def fetch(self) -> None:
        """Hash and look up the filtered files in parallel."""
        filtered_files = self.filtered_files
        if self.use_cached_metadata:
            logger.info(f"Loading metadata sidecars of {len(filtered_files)} files")
        else:
            logger.info(f"Fetching metadata for {len(filtered_files)} files")
        verb = "Loaded" if self.use_cached_metadata else "Looked up"

        # Hashing releases the GIL (hashlib), and API calls are additionally bounded
        # by api.batch.max_concurrent; the shared rate limiter, circuit breaker and
        # caches are thread-safe.
        batch_config = self.job_specific_config.get("api", {}).get("batch", {})
        parallel = batch_config.get("enabled", True)
        workers = (
            max(1, int(self.job_specific_config.get("scanner", {}).get("hash_workers", 4)))
            if parallel
            else 1
        )
        api_slots = threading.BoundedSemaphore(
            max(1, int(batch_config.get("max_concurrent", 4))) if parallel else 1
        )

        def fetch_one(file_path: str) -> Tuple[str, Optional[Dict[str, Any]]]:
            """Return (outcome, metadata) for one file."""
            try:
                if self.use_cached_metadata:
                    metadata = load_cached_metadata(file_path, self.job_specific_config)
                    if metadata:
                        logger.debug(f"Loaded cached metadata for {file_path}")
                        return "matched", metadata
                    logger.warning(f"No cached metadata found for {file_path}")
                    return "not_found", None

                result = self.processor.file_processor.process(
                    file_path, verify_hash=self.verify_hashes
                )
                if not result.success or not result.file_hash:
                    logger.warning(f"Failed to process file {file_path}: {result.error}")
                    return "unreadable", None

                if not self.force_refresh and self.processor.metadata_manager.is_known_not_found(
                    result.file_hash
                ):
                    return "not_found_cached", None

                with api_slots:
                    metadata = self.processor.metadata_manager.fetch_metadata(
                        result.file_hash, force_refresh=self.force_refresh
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
            if not self.use_cached_metadata:
                logger.info(f"Hashing and looking up with {workers} workers")
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(fetch_one, f): f for f in filtered_files}
                for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
                    outcome, metadata = future.result()
                    if metadata is not None:
                        fetched[futures[future]] = metadata
                    else:
                        self.summary[outcome] += 1
                    if done % 100 == 0 or done == len(filtered_files):
                        logger.info(f"{verb} {done}/{len(filtered_files)} files")
        else:
            for file_path in filtered_files:
                outcome, metadata = fetch_one(file_path)
                if metadata is not None:
                    fetched[file_path] = metadata
                else:
                    self.summary[outcome] += 1

        # Keep discovery order so later phases behave deterministically.
        for file_path in filtered_files:
            if file_path in fetched:
                self.metadata_dict[file_path] = fetched[file_path]

        self.processor.file_processor.flush()

    # --- Phase 1.5: sibling versions -------------------------------------------

    def enrich(self) -> None:
        """
        Add parent model data and sibling versions (deduplicated by modelId).

        Runs if any file's sibling versions are missing or stale (TTL). Skipped for
        offline cached-metadata jobs (e.g. regenerate-html), which must not hit the
        API.
        """
        if not self.metadata_dict or self.use_cached_metadata:
            return

        from ..scanner.version_enricher import VersionEnricher

        enricher = VersionEnricher(self.api_client, self.job_specific_config)
        if any(
            enricher.needs_enrichment(meta, self.force_refresh)
            for meta in self.metadata_dict.values()
        ):
            logger.info(f"Enriching {len(self.metadata_dict)} files with parent model data")
            self.metadata_dict = enricher.enrich_batch(
                self.metadata_dict, force_refresh=self.force_refresh
            )

    # --- Phase 2: organization -------------------------------------------------

    def organize(self) -> None:
        """Move/copy/link files into the organization output, if enabled."""
        organization_config = self.job_config.get("organization", {})
        if not (organization_config.get("enabled", False) and self.metadata_dict):
            return

        logger.info(f"Calculating target paths for {len(self.metadata_dict)} files")
        logger.debug(f"Using organization settings from job: {organization_config}")

        job_organizer = FileOrganizer(self.job_specific_config)

        logger.info(f"Organizing {len(self.metadata_dict)} files")
        organized_results = job_organizer.organize_files(
            list(self.metadata_dict.keys()), self.metadata_dict
        )

        for orig_path, new_path in organized_results:
            if new_path:
                self.organized_files_mapping[orig_path] = new_path

    # --- Phase 4a: sidecars + version index ------------------------------------

    def write_sidecars(self) -> None:
        """
        Write every sidecar, then rebuild the version index.

        Sidecars are flushed first (at the resolved, possibly organized path) so the
        per-model version union on each detail page is deterministic regardless of
        HTML generation order in ``render``.
        """
        # Images are downloaded per model in render() (in parallel, right before
        # that model's HTML is rendered), into the organized location if any.
        if self.metadata_dict and not self.job_specific_config.get("output", {}).get(
            "images", {}
        ).get("save", True):
            logger.info("Skipping image downloads (images.save is false)")

        logger.info(f"Processing {len(self.metadata_dict)} files with metadata")

        originals_needing_sidecar = []
        for file_path, metadata in self.metadata_dict.items():
            process_path = self.organized_files_mapping.get(file_path, file_path) or file_path
            self.items_to_process.append((process_path, metadata))
            if self.mirror_mode and process_path != file_path:
                originals_needing_sidecar.append((file_path, metadata))

        from ..html.context import _version_index_cache, invalidate_version_index

        metadata_manager = self.processor.metadata_manager
        dry_run = self.processor.dry_run

        # Copy/symlink mode: the original stays where it is and is what the next
        # scan finds, so it needs its own sidecar or skip_existing never skips it.
        # Written first (on a copy carrying the enricher's dirty flag) because
        # save_metadata consumes that flag.
        for original_path, metadata in originals_needing_sidecar:
            metadata_manager.save_metadata(original_path, dict(metadata), dry_run)

        # A model whose sidecar could not be written gets no page or previews (the
        # next scan retries it) and counts as failed in the summary.
        written = []
        for process_path, metadata in self.items_to_process:
            if metadata_manager.save_metadata(process_path, metadata, dry_run):
                written.append((process_path, metadata))
            else:
                self.results.append((process_path, None))
        self.items_to_process = written

        invalidate_version_index()
        if not dry_run:
            index_dirs = {
                os.path.dirname(os.path.abspath(get_metadata_path(p, self.job_specific_config)))
                for p, _ in self.items_to_process
            }
            for index_dir in index_dirs:
                _version_index_cache.ensure_indexed(index_dir)

    # --- Phase 4b: previews + detail pages -------------------------------------

    def render(self) -> None:
        """Download previews and generate detail pages (sidecars are already written)."""
        items = self.items_to_process
        processor = self.processor
        force_refresh = self.force_refresh

        if len(items) > 10:
            download_workers = (
                self.job_specific_config.get("api", {}).get("batch", {}).get("download_workers", 4)
            )
            max_workers = max(1, min(int(download_workers), len(items)))
            logger.info(f"Processing {len(items)} files with {max_workers} workers")

            def process_single_item(
                item: Tuple[str, Dict[str, Any]],
            ) -> Tuple[str, Optional[Dict[str, Any]]]:
                path, meta = item
                processed = processor.save_and_process_with_metadata(
                    path, meta, force_refresh=force_refresh
                )
                return (path, processed)

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {
                    executor.submit(process_single_item, item): item for item in items
                }
                completed = 0
                for future in concurrent.futures.as_completed(future_to_item):
                    completed += 1
                    try:
                        self.results.append(future.result())
                    except Exception as e:
                        item = future_to_item[future]
                        logger.error(f"Error processing {item[0]}: {e}")
                        self.results.append((item[0], None))

                    if completed % 50 == 0 or completed == len(items):
                        logger.info(f"Processed {completed}/{len(items)} files")
        else:
            for process_path, metadata in items:
                processed_metadata = processor.save_and_process_with_metadata(
                    process_path, metadata, force_refresh=force_refresh
                )
                self.results.append((process_path, processed_metadata))

    # --- Gallery ---------------------------------------------------------------

    def build_gallery(self) -> None:
        """Generate the gallery page, if enabled for this job."""
        # The merged config, like the model pages: a gallery_path set globally is
        # where the pages link to, so the gallery must be written there too.
        html_config = (
            self.job_specific_config.get("output", {}).get("metadata", {}).get("html", {})
        )
        if not html_config.get("generate_gallery", False):
            return

        gallery_path = html_config.get("gallery_path") or DEFAULT_GALLERY_PATH
        gallery_title = html_config.get("gallery_title", "Model Gallery")
        include_existing = html_config.get("include_existing_in_gallery", True)

        logger.info(f"Generating gallery at {gallery_path}")
        logger.debug(f"Include existing model cards: {include_existing}")

        # Store the path_ids in the config for use by find_html_files
        if include_existing:
            self.job_specific_config["gallery_path_ids"] = self.path_ids

        self.html_generator.generate_gallery(
            list(self.metadata_dict.keys()),
            gallery_path,
            gallery_title,
            include_existing=include_existing,
            unmatched=self.unmatched_files(),
        )

    def unmatched_files(self) -> List[Tuple[str, str]]:
        """
        List scanned model files that still have no sidecar, with the reason.

        "Not on CivitAI" only when CivitAI answered 404 for the file's (cached)
        hash; anything else (never looked up, temporary error, unreadable) is
        "no metadata".
        """
        processor = self.processor
        unmatched: List[Tuple[str, str]] = []
        for file_path in self.files:
            if file_path in self.metadata_dict or not os.path.isfile(file_path):
                continue
            if has_metadata(file_path, self.job_specific_config):
                continue
            file_hash = processor.file_processor.cached_hash(file_path)
            if file_hash and processor.metadata_manager.is_known_not_found(file_hash):
                unmatched.append((file_path, UNMATCHED_NOT_ON_CIVITAI))
            else:
                unmatched.append((file_path, UNMATCHED_NO_METADATA))
        return unmatched

    # --- Summary ---------------------------------------------------------------

    def log_summary(self) -> None:
        """Log what the job did."""
        summary = self.summary
        summary["output_failed"] = sum(1 for _, meta in self.results if meta is None)
        skipped = len(self.files) - len(self.filtered_files)
        if self.use_cached_metadata:
            # Offline job: files are skipped because they have NO sidecar yet, and
            # nothing is looked up on CivitAI.
            unreadable = summary["not_found"] + summary["errors"]
            logger.info(
                f"Job {self.job_name} summary: {len(self.files)} found, "
                f"{skipped} skipped (no metadata yet), "
                f"{len(self.metadata_dict)} loaded from sidecars, "
                f"{unreadable} sidecars unreadable, "
                f"{summary['output_failed']} failed while writing output"
            )
            return
        logger.info(
            f"Job {self.job_name} summary: {len(self.files)} found, "
            f"{skipped} skipped (already have metadata), "
            f"{len(self.metadata_dict)} matched, {summary['not_found']} not found on CivitAI "
            f"(+{summary['not_found_cached']} known unknown, not re-queried), "
            f"{summary['unreadable']} unreadable, {summary['errors']} lookup errors, "
            f"{summary['output_failed']} failed while writing output"
        )

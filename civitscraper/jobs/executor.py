"""
Job executor for CivitScraper.

This module handles executing jobs defined in the configuration.
"""

import logging
import os
from typing import Any, Dict, List

from ..api.client import CivitAIClient
from ..config.loader import merge_configs
from ..html.generator import HTMLGenerator
from ..organization import FileOrganizer
from ..scanner.discovery import filter_files, find_model_files
from ..scanner.processor import ModelProcessor

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

        # Create HTML generator
        self.html_generator = HTMLGenerator(config)

        # Create model processor and pass the HTML generator
        self.model_processor = ModelProcessor(config, api_client, self.html_generator)

        # Create file organizer
        self.file_organizer = FileOrganizer(config)

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

            # Find model files
            logger.info(f"Finding model files for paths: {path_ids}")
            # Use job's recursive setting if specified
            job_recursive = job_config.get("recursive")
            path_files = find_model_files(self.config, path_ids, job_recursive)

            # Flatten files
            files: List[str] = []
            for path_id, path_files_list in path_files.items():
                files.extend(path_files_list)

            # Filter files
            logger.info(f"Found {len(files)} files, filtering...")
            filtered_files = filter_files(files, skip_existing)
            logger.info(f"Filtered to {len(filtered_files)} files")

            # Use the job configuration directly
            job_specific_config = self.config.copy()

            # Apply job-specific configuration
            for key, value in job_config.items():
                if (
                    key in job_specific_config
                    and isinstance(job_specific_config[key], dict)
                    and isinstance(value, dict)
                ):
                    # For dictionary values, merge them
                    job_specific_config[key] = merge_configs(job_specific_config[key], value)
                else:
                    # For other values, override them
                    job_specific_config[key] = value

            # Create a temporary processor with the job-specific configuration
            temp_processor = ModelProcessor(
                job_specific_config, self.api_client, self.html_generator
            )

            # Get force_refresh setting from job-specific scanner configuration
            force_refresh = job_config.get("force_refresh", False)
            if not force_refresh:
                force_refresh = job_specific_config.get("scanner", {}).get("force_refresh", False)

            # PHASE 1: Fetch metadata
            logger.info(f"Fetching metadata for {len(filtered_files)} files")
            metadata_dict = {}
            organized_files_mapping = {}

            # First, fetch metadata for all files without processing them
            for file_path in filtered_files:
                try:
                    result = temp_processor.file_processor.process(
                        file_path, verify_hash=verify_hashes
                    )
                    if not result.success or not result.file_hash:
                        logger.warning(f"Failed to process file {file_path}: {result.error}")
                        continue

                    # Get metadata from API
                    metadata = temp_processor.metadata_manager.fetch_metadata(
                        result.file_hash, force_refresh=force_refresh
                    )
                    if metadata:
                        logger.debug(f"Got metadata for {file_path}")
                        metadata_dict[file_path] = metadata
                    else:
                        logger.warning(f"No metadata found for {file_path}")
                except Exception as e:
                    logger.error(f"Error fetching metadata for {file_path}: {e}")

            # PHASE 2: Calculate target paths if organization is enabled
            organization_config = job_config.get("organization", {})
            if organization_config.get("enabled", False) and metadata_dict:
                logger.info(f"Calculating target paths for {len(metadata_dict)} files")
                logger.debug(f"Using organization settings from job: {organization_config}")

                # Create a job-specific organizer with the updated configuration
                job_organizer = FileOrganizer(job_specific_config)

                # Get target paths for all files
                target_paths = job_organizer.get_target_paths(
                    list(metadata_dict.keys()), metadata_dict
                )

                # Create directories for target paths
                for target_path in target_paths.values():
                    target_dir = os.path.dirname(target_path)
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir, exist_ok=True)

                # Organize pre-existing files
                logger.info(f"Organizing {len(metadata_dict)} files")
                organized_results = job_organizer.organize_files(
                    list(metadata_dict.keys()), metadata_dict
                )

                # Create mapping from original path to new path
                for orig_path, new_path in organized_results:
                    if new_path:
                        organized_files_mapping[orig_path] = new_path

            # PHASE 3: Download images to appropriate paths
            if metadata_dict:
                logger.info(f"Downloading images for {len(metadata_dict)} files")
                for file_path, metadata in metadata_dict.items():
                    # Use organized path if available, otherwise use original path
                    target_path = organized_files_mapping.get(file_path, file_path)
                    temp_processor.image_manager.download_images(
                        target_path, metadata, force_refresh=force_refresh
                    )

            # PHASE 4: Process remaining tasks (metadata, HTML)
            logger.info(f"Processing {len(metadata_dict)} files with metadata")
            results = []

            for file_path, metadata in metadata_dict.items():
                # Determine which path to use for processing
                process_path = organized_files_mapping.get(file_path, file_path)
                if process_path:
                    # Save and process with metadata
                    processed_metadata = temp_processor.save_and_process_with_metadata(
                        process_path, metadata
                    )
                    results.append((process_path, processed_metadata))
                else:
                    # If organization failed, use original path
                    processed_metadata = temp_processor.save_and_process_with_metadata(
                        file_path, metadata
                    )
                    results.append((file_path, processed_metadata))

            # PHASE 4: Generate gallery
            html_config = job_config.get("output", {}).get("metadata", {}).get("html", {})
            if html_config.get("generate_gallery", False):
                gallery_path = html_config.get("gallery_path", "gallery.html")
                gallery_title = html_config.get("gallery_title", "Model Gallery")
                include_existing = html_config.get("include_existing_in_gallery", True)

                logger.info(f"Generating gallery at {gallery_path}")
                logger.debug(f"Include existing model cards: {include_existing}")

                # Create a temporary HTML generator with the job-specific configuration
                # and pass the path_ids to use for finding existing HTML files
                temp_html_generator = HTMLGenerator(job_specific_config)

                # Store the path_ids in the config for use by find_html_files
                if include_existing:
                    job_specific_config["gallery_path_ids"] = path_ids

                temp_html_generator.generate_gallery(
                    list(metadata_dict.keys()),
                    gallery_path,
                    gallery_title,
                    include_existing=include_existing,
                )

            return True

        except Exception as e:
            logger.error(f"Error executing scan-paths job {job_name}: {e}")
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

            # Get scan options

            # Find model files
            logger.info(f"Finding model files for paths: {path_ids}")
            # Use job's recursive setting if specified
            job_recursive = job_config.get("recursive")
            path_files = find_model_files(self.config, path_ids, job_recursive)

            # Flatten files
            files: List[str] = []
            for path_id, path_files_list in path_files.items():
                files.extend(path_files_list)

            # Filter to LORA files
            lora_files = []
            for file_path in files:
                # Get metadata path
                metadata_path = os.path.splitext(file_path)[0] + ".json"

                # Check if metadata exists
                if not os.path.isfile(metadata_path):
                    continue

                # Add to LORA files
                lora_files.append(file_path)

            # Check if loras.json exists
            if not os.path.isfile(loras_file):
                logger.error(f"loras.json not found at {loras_file}")
                return False

            # Load loras.json
            import json

            with open(loras_file, "r") as f:
                loras_data = json.load(f)

            # Update loras.json
            updated_count = 0
            processed_count = 0
            logger.debug(f"Total files to process: {len(lora_files)}")

            for file_path in lora_files:
                processed_count += 1
                logger.debug(f"Processing {file_path}")

                # Get metadata path
                metadata_path = os.path.splitext(file_path)[0] + ".json"

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
                        current_triggers = entry.get("metadata", {}).get("lora_triggers", "None")
                        if current_triggers != "None":
                            logger.debug(
                                f"Found pre-existing triggers for {filename}: {current_triggers}"
                            )
                        logger.debug(f"Updating with new triggers: {trigger_words}")

                        # Update entry
                        if "metadata" not in entry:
                            entry["metadata"] = {}

                        entry["metadata"]["lora_triggers"] = trigger_words
                        updated_count += 1
                        break
                else:
                    logger.debug(f"No matching entry found in loras.json for {filename}")

            # Save loras.json
            with open(loras_file, "w") as f:
                json.dump(loras_data, f, indent=2)

            logger.info(f"Files processed: {processed_count}")
            logger.info(f"Updated {updated_count} entries in loras.json")

            return True

        except Exception as e:
            logger.error(f"Error executing sync-lora-triggers job {job_name}: {e}")
            return False

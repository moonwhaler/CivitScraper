"""
Job executor for CivitScraper.

This module handles executing jobs defined in the configuration.
"""

import logging
import os
from typing import Any, Dict, List

from ..api.client import CivitAIClient
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
        logger.debug(f"Job configuration for {job_name} before execution: {job_config}")

        # Check if the job uses a template
        template_name = job_config.get("template")
        if template_name:
            # Log the template name
            logger.debug(f"Job {job_name} uses template: {template_name}")

            # Get the template configuration
            template_config = self.config.get("job_templates", {}).get(template_name)
            if template_config:
                # Log the template configuration
                logger.debug(f"Template {template_name} configuration: {template_config}")

                # Check if the template has an output section with max_count
                template_max_count = (
                    template_config.get("output", {}).get("images", {}).get("max_count")
                )
                if template_max_count:
                    logger.debug(f"Template {template_name} has max_count: {template_max_count}")

                    # Check if the job has an output section
                    if "output" not in job_config:
                        # Add the output section from the template to the job configuration
                        logger.debug(
                            f"Adding output section from template {template_name} to job {job_name}"
                        )
                        job_config["output"] = template_config.get("output", {})

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
            organize = job_config.get("organize", False)

            # Find model files
            logger.info(f"Finding model files for paths: {path_ids}")
            path_files = find_model_files(self.config, path_ids)

            # Flatten files
            files: List[str] = []
            for path_id, path_files_list in path_files.items():
                files.extend(path_files_list)

            # Filter files
            logger.info(f"Found {len(files)} files, filtering...")
            filtered_files = filter_files(files, skip_existing)
            logger.info(f"Filtered to {len(filtered_files)} files")

            # Process files
            logger.info(f"Processing {len(filtered_files)} files")

            # Always create a job-specific processor to ensure we use the correct configuration
            # Create a copy of the global configuration
            job_specific_config = self.config.copy()

            # Get the job configuration directly from the job_config parameter
            # This should be the fully resolved configuration after inheritance

            # Log the configuration for debugging
            logger.debug(f"Job configuration for {job_name}: {job_config}")

            # Log the max_count values for debugging
            global_max_count = (
                job_specific_config.get("output", {}).get("images", {}).get("max_count", "not set")
            )
            job_max_count = (
                job_config.get("output", {}).get("images", {}).get("max_count", "not set")
            )
            logger.debug(f"Global max_count: {global_max_count}, Job max_count: {job_max_count}")

            # If the job has an output section, use it
            if "output" in job_config:
                logger.debug(f"Using job-specific output configuration for job: {job_name}")
                # Override the output configuration with the job-specific one
                job_specific_config["output"] = job_config["output"]

                # Log the max_count value after update
                updated_max_count = (
                    job_specific_config.get("output", {})
                    .get("images", {})
                    .get("max_count", "not set")
                )
                logger.debug(f"Updated max_count: {updated_max_count}")
            else:
                logger.debug(f"No output section found in job configuration for {job_name}")

            # Create a temporary processor with the job-specific configuration
            temp_processor = ModelProcessor(
                job_specific_config, self.api_client, self.html_generator
            )

            # Get force_refresh setting from job-specific scanner configuration
            force_refresh = job_specific_config.get("scanner", {}).get("force_refresh", False)

            # Use the temporary processor
            results = temp_processor.process_files_in_batches(
                filtered_files,
                verify_hash=verify_hashes,
                force_refresh=force_refresh,
            )

            # Create metadata dictionary
            metadata_dict = {}
            for file_path, metadata in results:
                if metadata:
                    metadata_dict[file_path] = metadata

            # Organize files
            if organize:
                logger.info(f"Organizing {len(metadata_dict)} files")

                # Check if we need to use the default organization settings
                if not job_config.get("organization"):
                    # If organization is empty in job config, use the defaults
                    if "defaults" in self.config and "organization" in self.config["defaults"]:
                        logger.debug(
                            "Using default organization settings because job organization is empty"
                        )
                        job_specific_config["organization"] = self.config["defaults"][
                            "organization"
                        ]

                # Create a job-specific organizer with the updated configuration
                job_organizer = FileOrganizer(job_specific_config)
                job_organizer.organize_files(
                    list(metadata_dict.keys()), metadata_dict, force_organize=True
                )

            # Generate gallery
            if job_config.get("generate_gallery", False):
                gallery_path = job_config.get("gallery_path", "gallery.html")
                gallery_title = job_config.get("gallery_title", "Model Gallery")

                logger.info(f"Generating gallery at {gallery_path}")
                self.html_generator.generate_gallery(
                    list(metadata_dict.keys()), gallery_path, gallery_title
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
            path_files = find_model_files(self.config, path_ids)

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
            for file_path in lora_files:
                # Get metadata path
                metadata_path = os.path.splitext(file_path)[0] + ".json"

                # Load metadata
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)

                # Get activation text
                activation_text = metadata.get("activation text")
                if not activation_text:
                    continue

                # Get relative path
                relative_path = os.path.relpath(file_path)

                # Find entry in loras.json
                for entry in loras_data:
                    if entry.get("id") == relative_path:
                        # Update entry
                        if "metadata" not in entry:
                            entry["metadata"] = {}

                        entry["metadata"]["lora_triggers"] = activation_text
                        updated_count += 1
                        break

            # Save loras.json
            with open(loras_file, "w") as f:
                json.dump(loras_data, f, indent=2)

            logger.info(f"Updated {updated_count} entries in loras.json")

            return True

        except Exception as e:
            logger.error(f"Error executing sync-lora-triggers job {job_name}: {e}")
            return False

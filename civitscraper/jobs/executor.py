"""
Job executor for CivitScraper.

This module looks up jobs defined in the configuration and runs them.
"""

import logging
from typing import Any, Dict

from ..api.client import CivitAIClient
from ..sorting.job import SortJob
from ..updates.job import UpdateJob
from .lora_sync import LoraTriggerSync
from .scan_job import ScanJob

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
        job_config = self.config.get("jobs", {}).get(job_name)
        if not job_config:
            logger.error(f"Job not found: {job_name}")
            return False

        logger.debug(f"Job configuration for {job_name}: {job_config}")

        job_type = job_config.get("type")
        if not job_type:
            logger.error(f"No job type specified for job: {job_name}")
            return False

        if job_type == "scan-paths":
            return ScanJob(self.config, job_name, job_config, self.api_client).run()
        elif job_type == "sort-models":
            return SortJob(self.config, job_name, job_config, run_job=self.execute_job).run()
        elif job_type == "download-updates":
            return UpdateJob(
                self.config, job_name, job_config, self.api_client, run_job=self.execute_job
            ).run()
        elif job_type == "sync-lora-triggers":
            # Offline job: needs no API client.
            return LoraTriggerSync(self.config, job_name, job_config).run()
        else:
            logger.error(f"Unknown job type: {job_type}")
            return False

    def execute_all_jobs(self) -> Dict[str, bool]:
        """
        Execute all jobs.

        Returns:
            Dictionary of job name -> success
        """
        results = {}

        for job_name in self.config.get("jobs", {}):
            logger.info(f"Executing job: {job_name}")
            success = self.execute_job(job_name)
            results[job_name] = success

            if success:
                logger.info(f"Job {job_name} executed successfully")
            else:
                logger.error(f"Job {job_name} failed")

        return results

"""
Command-line interface for CivitScraper.

This module provides the command-line interface for the application.
"""

import argparse
import logging
import sys

from .api.client import CivitAIClient
from .config.loader import load_and_validate_config
from .jobs.executor import JobExecutor
from .utils.logging import setup_logging

logger = logging.getLogger(__name__)


def parse_args():
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="CivitScraper - A tool for fetching and managing CivitAI model metadata"
    )

    # Configuration
    parser.add_argument("-c", "--config", help="Path to configuration file")

    # Job execution
    parser.add_argument("-j", "--job", help="Execute a specific job")
    parser.add_argument("--all-jobs", action="store_true", help="Execute all jobs")

    # Organization
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulate file operations without making changes"
    )

    # Cache
    parser.add_argument(
        "--force-refresh", action="store_true", help="Ignore cache and force refresh metadata"
    )

    # Logging
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--quiet", action="store_true", help="Suppress console output")

    return parser.parse_args()


def main():
    """Run the main application."""
    args = parse_args()

    logger = logging.getLogger(__name__)

    try:
        config = load_and_validate_config(args.config)

        logger = setup_logging(config)

        # Override configuration with command-line arguments
        if args.dry_run:
            # Set dry_run at the top level of the configuration only
            config["dry_run"] = True

        if args.force_refresh:
            # Set force_refresh in the scanner section
            if "scanner" not in config:
                config["scanner"] = {}
            config["scanner"]["force_refresh"] = True

        # Set up logging
        if args.debug:
            if "logging" not in config:
                config["logging"] = {}
            config["logging"]["level"] = "DEBUG"

            # Also set console logging level
            if "console" not in config["logging"]:
                config["logging"]["console"] = {}
            config["logging"]["console"]["level"] = "DEBUG"

        if args.quiet:
            if "logging" not in config:
                config["logging"] = {}
            if "console" not in config["logging"]:
                config["logging"]["console"] = {}
            config["logging"]["console"]["enabled"] = False

        logger = setup_logging(config)

        if args.force_refresh:
            logger.info("Force refresh enabled: Cache will be ignored")

        api_client = CivitAIClient(config)

        job_executor = JobExecutor(config, api_client)

        # Execute jobs
        if args.job:
            logger.info(f"Executing job: {args.job}")
            success = job_executor.execute_job(args.job)

            if success:
                logger.info(f"Job {args.job} executed successfully")
                return 0
            else:
                logger.error(f"Job {args.job} failed")
                return 1

        elif args.all_jobs:
            logger.info("Executing all jobs")
            results = job_executor.execute_all_jobs()

            if all(results.values()):
                logger.info("All jobs executed successfully")
                return 0
            else:
                failed_jobs = [job_name for job_name, success in results.items() if not success]
                logger.error(f"The following jobs failed: {', '.join(failed_jobs)}")
                return 1

        else:
            default_job = config.get("default_job")
            if default_job:
                logger.info(f"Executing default job: {default_job}")
                success = job_executor.execute_job(default_job)

                if success:
                    logger.info(f"Default job {default_job} executed successfully")
                    return 0
                else:
                    logger.error(f"Default job {default_job} failed")
                    return 1
            else:
                logger.error("No job specified and no default job configured")
                return 1

    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

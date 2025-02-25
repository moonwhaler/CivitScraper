"""
Command-line interface for CivitScraper.

This module provides the command-line interface for the application.
"""

import os
import sys
import argparse
import logging
from typing import Dict, Any, List, Optional, Tuple

from .config.loader import load_and_validate_config
from .api.client import CivitAIClient
from .jobs.executor import JobExecutor
from .utils.logging import setup_logging

logger = logging.getLogger(__name__)


def parse_args():
    """
    Parse command-line arguments.
    
    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(description="CivitScraper - A tool for fetching and managing CivitAI model metadata")
    
    # Configuration
    parser.add_argument("-c", "--config", help="Path to configuration file")
    
    # Job execution
    parser.add_argument("-j", "--job", help="Execute a specific job")
    parser.add_argument("--all-jobs", action="store_true", help="Execute all jobs")
    
    # Organization
    parser.add_argument("--dry-run", action="store_true", help="Simulate file operations without making changes")
    
    # Logging
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--quiet", action="store_true", help="Suppress console output")
    
    return parser.parse_args()


def main():
    """
    Main entry point for the application.
    """
    # Parse command-line arguments
    args = parse_args()
    
    try:
        # Load configuration
        config = load_and_validate_config(args.config)
        
        # Override configuration with command-line arguments
        if args.dry_run:
            # Set dry_run at the top level of the configuration
            config["dry_run"] = True
            
            # Also set it in the organization section for backward compatibility
            if "organization" not in config:
                config["organization"] = {}
            config["organization"]["dry_run"] = True
        
        # Set up logging
        if args.debug:
            if "logging" not in config:
                config["logging"] = {}
            config["logging"]["level"] = "DEBUG"
        
        if args.quiet:
            if "logging" not in config:
                config["logging"] = {}
            if "console" not in config["logging"]:
                config["logging"]["console"] = {}
            config["logging"]["console"]["enabled"] = False
        
        # Set up logging
        logger = setup_logging(config)
        
        # Create API client
        api_client = CivitAIClient(config)
        
        # Create job executor
        job_executor = JobExecutor(config, api_client)
        
        # Execute jobs
        if args.job:
            # Execute specific job
            logger.info(f"Executing job: {args.job}")
            success = job_executor.execute_job(args.job)
            
            if success:
                logger.info(f"Job {args.job} executed successfully")
                return 0
            else:
                logger.error(f"Job {args.job} failed")
                return 1
        
        elif args.all_jobs:
            # Execute all jobs
            logger.info("Executing all jobs")
            results = job_executor.execute_all_jobs()
            
            # Check if any job failed
            if all(results.values()):
                logger.info("All jobs executed successfully")
                return 0
            else:
                failed_jobs = [job_name for job_name, success in results.items() if not success]
                logger.error(f"The following jobs failed: {', '.join(failed_jobs)}")
                return 1
        
        else:
            # No job specified, execute default job
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

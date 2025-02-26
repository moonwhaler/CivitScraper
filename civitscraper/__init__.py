"""
CivitScraper - A tool for fetching and managing CivitAI model metadata.

This package provides functionality for:
- Scanning directories for model files
- Fetching metadata from CivitAI
- Organizing files based on metadata
- Generating HTML pages for models
- Synchronizing trigger words
"""

__version__ = "0.1.0"

from .config.loader import load_and_validate_config
from .api.client import CivitAIClient
from .scanner.discovery import find_model_files, filter_files
from .scanner.processor import ModelProcessor
from .html.generator import HTMLGenerator
from .organization.organizer import FileOrganizer
from .jobs.executor import JobExecutor
from .jobs.templates import get_job_template, get_all_job_templates, create_job_from_template
from .utils.logging import setup_logging

__all__ = [
    "load_and_validate_config",
    "CivitAIClient",
    "find_model_files",
    "filter_files",
    "ModelProcessor",
    "HTMLGenerator",
    "FileOrganizer",
    "JobExecutor",
    "get_job_template",
    "get_all_job_templates",
    "create_job_from_template",
    "setup_logging",
]

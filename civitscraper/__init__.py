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

from .api.client import CivitAIClient
from .config.loader import load_and_validate_config
from .html.generator import HTMLGenerator
from .jobs.executor import JobExecutor
# Removed templates module imports as part of job inheritance refactoring
from .organization.organizer import FileOrganizer
from .scanner.discovery import filter_files, find_model_files
from .scanner.processor import ModelProcessor
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
    "setup_logging",
]

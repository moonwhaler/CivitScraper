"""
Scanner package for CivitScraper.

This package handles scanning for model files, processing them, and generating metadata.
"""

from .batch_processor import BatchProcessor
from .discovery import (
    filter_files,
    find_files,
    find_model_files,
    get_html_path,
    get_image_path,
    get_metadata_path,
    get_model_type,
    has_metadata,
)
from .file_processor import FileProcessingResult, ModelFileProcessor
from .html_manager import HTMLManager
from .image_manager import ImageManager
from .metadata_manager import MetadataManager
from .processor import ModelProcessor, ProcessingResult

__all__ = [
    "ModelProcessor",
    "ProcessingResult",
    "ModelFileProcessor",
    "FileProcessingResult",
    "MetadataManager",
    "ImageManager",
    "HTMLManager",
    "BatchProcessor",
    "find_files",
    "find_model_files",
    "has_metadata",
    "get_metadata_path",
    "get_model_type",
    "get_html_path",
    "get_image_path",
    "filter_files",
]

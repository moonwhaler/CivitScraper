"""
Scanner package for CivitScraper.

This package handles scanning for model files, processing them, and generating metadata.
"""

from .processor import ModelProcessor, ProcessingResult
from .file_processor import ModelFileProcessor, FileProcessingResult
from .metadata_manager import MetadataManager
from .image_manager import ImageManager
from .html_manager import HTMLManager
from .batch_processor import BatchProcessor
from .discovery import (
    find_files,
    find_model_files,
    has_metadata,
    get_metadata_path,
    get_model_type,
    get_html_path,
    get_image_path,
    filter_files,
)

__all__ = [
    'ModelProcessor',
    'ProcessingResult',
    'ModelFileProcessor',
    'FileProcessingResult',
    'MetadataManager',
    'ImageManager',
    'HTMLManager',
    'BatchProcessor',
    'find_files',
    'find_model_files',
    'has_metadata',
    'get_metadata_path',
    'get_model_type',
    'get_html_path',
    'get_image_path',
    'filter_files',
]

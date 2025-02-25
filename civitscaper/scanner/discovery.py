"""
File discovery for CivitScraper.

This module handles discovering model files in the configured directories.
"""

import os
import glob
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)


def find_files(directory: str, patterns: List[str], recursive: bool = True) -> List[str]:
    """
    Find files matching patterns in directory.
    
    Args:
        directory: Directory to search
        patterns: File patterns to match
        recursive: Whether to search recursively
        
    Returns:
        List of matching file paths
    """
    # Normalize directory path
    directory = os.path.normpath(directory)
    
    # Check if directory exists
    if not os.path.isdir(directory):
        logger.error(f"Directory not found: {directory}")
        return []
    
    # Find files
    matching_files = []
    
    for pattern in patterns:
        # Create glob pattern
        if recursive:
            glob_pattern = os.path.join(directory, "**", pattern)
        else:
            glob_pattern = os.path.join(directory, pattern)
        
        # Find matching files
        for file_path in glob.glob(glob_pattern, recursive=recursive):
            # Check if file exists and is a file
            if os.path.isfile(file_path):
                matching_files.append(file_path)
    
    return matching_files


def find_model_files(config: Dict[str, Any], path_ids: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """
    Find model files in configured directories.
    
    Args:
        config: Configuration
        path_ids: List of path IDs to search, or None for all
        
    Returns:
        Dictionary of path ID -> list of file paths
    """
    # Get input paths
    input_paths = config.get("input_paths", {})
    
    # If no path IDs specified, use all
    if path_ids is None:
        path_ids = list(input_paths.keys())
    
    # Find files for each path
    result = {}
    
    for path_id in path_ids:
        # Check if path ID exists
        if path_id not in input_paths:
            logger.error(f"Path ID not found: {path_id}")
            continue
        
        # Get path configuration
        path_config = input_paths[path_id]
        
        # Get directory
        directory = path_config.get("path")
        if not directory:
            logger.error(f"No path specified for path ID: {path_id}")
            continue
        
        # Get patterns
        patterns = path_config.get("patterns", ["*.safetensors"])
        
        # Get recursive flag
        recursive = path_config.get("recursive", True)
        
        # Find files
        logger.info(f"Scanning directory: {directory}")
        files = find_files(directory, patterns, recursive)
        
        # Add to result
        result[path_id] = files
        
        logger.info(f"Found {len(files)} files in {directory}")
    
    return result


def has_metadata(file_path: str) -> bool:
    """
    Check if file has metadata.
    
    Args:
        file_path: Path to file
        
    Returns:
        True if file has metadata, False otherwise
    """
    # Get metadata file path
    metadata_path = os.path.splitext(file_path)[0] + ".json"
    
    # Check if metadata file exists
    return os.path.isfile(metadata_path)


def get_metadata_path(file_path: str, config: Dict[str, Any]) -> str:
    """
    Get metadata file path for model file.
    
    Args:
        file_path: Path to model file
        config: Configuration
        
    Returns:
        Path to metadata file
    """
    # Get output configuration
    output_config = config.get("output", {}).get("metadata", {})
    
    # Get path template
    path_template = output_config.get("path", "{model_dir}")
    
    # Get filename template
    filename_template = output_config.get("filename", "{model_name}.json")
    
    # Get model directory
    model_dir = os.path.dirname(file_path)
    
    # Get model name
    model_name = os.path.splitext(os.path.basename(file_path))[0]
    
    # Get model type
    model_type = get_model_type(file_path, config)
    
    # Format path
    path = path_template.replace("{model_dir}", model_dir)
    path = path.replace("{model_name}", model_name)
    path = path.replace("{model_type}", model_type)
    
    # Format filename
    filename = filename_template.replace("{model_name}", model_name)
    filename = filename.replace("{model_type}", model_type)
    
    # Combine path and filename
    return os.path.join(path, filename)


def get_model_type(file_path: str, config: Dict[str, Any]) -> str:
    """
    Get model type for file.
    
    Args:
        file_path: Path to model file
        config: Configuration
        
    Returns:
        Model type
    """
    # Get input paths
    input_paths = config.get("input_paths", {})
    
    # Check each path
    for path_id, path_config in input_paths.items():
        # Get directory
        directory = path_config.get("path")
        if not directory:
            continue
        
        # Normalize directory path
        directory = os.path.normpath(directory)
        
        # Check if file is in directory
        if os.path.normpath(file_path).startswith(directory):
            # Get model type
            return path_config.get("type", "Unknown")
    
    return "Unknown"


def get_html_path(file_path: str, config: Dict[str, Any]) -> str:
    """
    Get HTML file path for model file.
    
    Args:
        file_path: Path to model file
        config: Configuration
        
    Returns:
        Path to HTML file
    """
    # Get output configuration
    output_config = config.get("output", {}).get("metadata", {}).get("html", {})
    
    # Get path template
    path_template = output_config.get("path", "{model_dir}")
    
    # Get filename template
    filename_template = output_config.get("filename", "{model_name}.html")
    
    # Get model directory
    model_dir = os.path.dirname(file_path)
    
    # Get model name
    model_name = os.path.splitext(os.path.basename(file_path))[0]
    
    # Get model type
    model_type = get_model_type(file_path, config)
    
    # Format path
    path = path_template.replace("{model_dir}", model_dir)
    path = path.replace("{model_name}", model_name)
    path = path.replace("{model_type}", model_type)
    
    # Format filename
    filename = filename_template.replace("{model_name}", model_name)
    filename = filename.replace("{model_type}", model_type)
    
    # Combine path and filename
    return os.path.join(path, filename)


def get_image_path(file_path: str, config: Dict[str, Any], image_type: str = "preview", ext: str = ".jpg") -> str:
    """
    Get image file path for model file.
    
    Args:
        file_path: Path to model file
        config: Configuration
        image_type: Image type (e.g., preview)
        ext: Image file extension
        
    Returns:
        Path to image file
    """
    # Get output configuration
    output_config = config.get("output", {}).get("images", {})
    
    # Get path template
    path_template = output_config.get("path", "{model_dir}")
    
    # Get filename template
    # Strip any numbers from the end of the image type (e.g., "preview0" -> "preview")
    base_image_type = ''.join([c for c in image_type if not c.isdigit()])
    filename_template = output_config.get("filenames", {}).get(
        base_image_type, "{model_name}.{image_type}{ext}"
    )
    
    # Get model directory
    model_dir = os.path.dirname(file_path)
    
    # Get model name
    model_name = os.path.splitext(os.path.basename(file_path))[0]
    
    # Get model type
    model_type = get_model_type(file_path, config)
    
    # Format path
    path = path_template.replace("{model_dir}", model_dir)
    path = path.replace("{model_name}", model_name)
    path = path.replace("{model_type}", model_type)
    
    # Format filename
    filename = filename_template.replace("{model_name}", model_name)
    filename = filename.replace("{model_type}", model_type)
    filename = filename.replace("{image_type}", image_type)
    filename = filename.replace("{ext}", ext)
    
    # Combine path and filename
    return os.path.join(path, filename)


def filter_files(files: List[str], skip_existing: bool = True) -> List[str]:
    """
    Filter files based on criteria.
    
    Args:
        files: List of file paths
        skip_existing: Whether to skip files that already have metadata
        
    Returns:
        Filtered list of file paths
    """
    # Filter files
    filtered_files = []
    
    for file_path in files:
        # Check if file should be skipped
        if skip_existing and has_metadata(file_path):
            logger.debug(f"Skipping file with existing metadata: {file_path}")
            continue
        
        # Add to filtered files
        filtered_files.append(file_path)
    
    return filtered_files

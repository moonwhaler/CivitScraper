"""
File discovery for CivitScraper.

This module handles discovering model files in the configured directories.
"""

import glob
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

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


def find_model_files(
    config: Dict[str, Any],
    path_ids: Optional[List[str]] = None,
    job_recursive: Optional[bool] = None,
) -> Dict[str, List[str]]:
    """
    Find model files in configured directories.

    Args:
        config: Configuration
        path_ids: List of path IDs to search, or None for all
        job_recursive: Override setting from job config (takes precedence over path config)

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

        # Get recursive flag - job_recursive overrides path_config if provided
        if job_recursive is not None:
            recursive = job_recursive
            logger.debug(f"Using job recursive setting: {recursive} for path {path_id}")
        else:
            recursive = path_config.get("recursive", True)
            logger.debug(f"Using path recursive setting: {recursive} for path {path_id}")

        # Find files
        logger.info(f"Scanning directory: {directory} (recursive: {recursive})")
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

    model_type: str = get_model_type(file_path, config)

    # Format path
    path = path_template.replace("{model_dir}", model_dir)
    path = path.replace("{model_name}", model_name)
    path = path.replace("{model_type}", model_type)

    # Format filename
    filename = filename_template.replace("{model_name}", model_name)
    filename = filename.replace("{model_type}", model_type)

    # Combine path and filename and ensure it's a string
    result = os.path.join(path, filename)
    return str(result)


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
    if not input_paths or not isinstance(input_paths, dict):
        return "Unknown"

    # Check each path
    for path_id, path_config in input_paths.items():
        if not isinstance(path_config, dict):
            continue

        # Get directory
        directory = path_config.get("path")
        if not directory or not isinstance(directory, str):
            continue

        # Normalize directory path
        directory = os.path.normpath(directory)

        # Check if file is in directory
        if os.path.normpath(file_path).startswith(directory):
            # Get model type
            model_type = path_config.get("type")
            if model_type is not None and isinstance(model_type, str):
                return str(model_type)
            else:
                return "Unknown"

    # If no match found, return a default string
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

    # Combine path and filename and ensure it's a string
    result = os.path.join(path, filename)
    return str(result)


def get_image_path(
    file_path: str, config: Dict[str, Any], image_type: str = "preview", ext: str = ".jpg"
) -> str:
    """
    Get image file path for model file.

    Args:
        file_path: Path to model file
        config: Configuration
        image_type: Image type (e.g., preview, preview0, preview1, etc.)
        ext: Image file extension

    Returns:
        Path to image file
    """
    # Get output configuration
    output_config = config.get("output", {}).get("images", {})

    # Get path template
    path_template = output_config.get("path", "{model_dir}")

    # Extract the base image type and index number
    import re

    match = re.match(r"([a-zA-Z_]+)(\d*)", image_type)
    if match:
        base_image_type = match.group(1)  # The non-digit part (e.g., "preview")
        index_number = match.group(2)  # The digit part (e.g., "0", "1", etc.)
    else:
        base_image_type = image_type  # No digits found, use the full image_type
        index_number = ""

    # Get the filename template using the base image type
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
    filename = filename.replace(
        "{image_type}", base_image_type
    )  # Use base_image_type without index
    filename = filename.replace("{ext}", ext)

    # Insert the index number before the extension
    if index_number:
        # Find the position of the extension in the filename
        ext_pos = filename.rfind(ext)
        if ext_pos != -1:
            # Insert the index number before the extension
            filename = filename[:ext_pos] + index_number + filename[ext_pos:]

    # Combine path and filename and ensure it's a string
    result = os.path.join(path, filename)
    return str(result)


def find_html_files(
    config: Dict[str, Any],
    path_ids: Optional[List[str]] = None,
    job_recursive: Optional[bool] = None,
) -> List[str]:
    """
    Find existing model card HTML files in configured directories.

    Args:
        config: Configuration
        path_ids: List of path IDs to search, or None for all
        job_recursive: Override recursive setting from job config

    Returns:
        List of valid model card HTML file paths, prioritizing organized locations
    """
    # Get input paths
    input_paths = config.get("input_paths", {})

    # If no path IDs specified, use all
    if path_ids is None:
        path_ids = list(input_paths.keys())

    # Dictionary to store unique model cards, keyed by model name
    # Value is a tuple of (html_path, is_organized)
    unique_models: Dict[str, Tuple[str, bool]] = {}

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

        # Get recursive flag - job_recursive overrides path_config if provided
        if job_recursive is not None:
            recursive = job_recursive
            logger.debug(
                f"Using job recursive setting: {recursive} for HTML search in path {path_id}"
            )
        else:
            recursive = path_config.get("recursive", True)
            logger.debug(
                f"Using path recursive setting: {recursive} for HTML search in path {path_id}"
            )

        # Build a list of directories to scan
        directories_to_scan = []

        # Check if organization is enabled and add organized directories first
        organization_config = config.get("organization", {})
        if organization_config.get("enabled", False):
            # Get output directory template
            output_dir = organization_config.get("output_dir", "{model_dir}/organized")
            if "{model_dir}" in output_dir:
                # Replace {model_dir} with the actual directory
                organized_dir = output_dir.replace("{model_dir}", directory)
                if os.path.isdir(organized_dir):
                    directories_to_scan.append((organized_dir, True))
                    logger.debug(f"Adding organized directory to scan: {organized_dir}")

        # Add original directory last (lower priority)
        directories_to_scan.append((directory, False))

        # Scan all directories
        for scan_dir, is_organized in directories_to_scan:
            # Find HTML files
            logger.debug(f"Scanning directory for HTML files: {scan_dir}")
            files = find_files(scan_dir, ["*.html"], recursive)

            # Filter to only include valid model card HTML files
            for html_file in files:
                # Check if this is a model card HTML file by looking for a metadata file
                html_dir = os.path.dirname(html_file)
                html_basename = os.path.basename(html_file)
                model_name = os.path.splitext(html_basename)[0]

                # Look for a metadata file with the same base name
                metadata_path = os.path.join(html_dir, f"{model_name}.json")

                if os.path.isfile(metadata_path):
                    # Check if we already have this model
                    if model_name not in unique_models or (
                        is_organized and not unique_models[model_name][1]
                    ):
                        # Add model if it's new or if this is an organized version
                        unique_models[model_name] = (html_file, is_organized)
                        logger.debug(
                            f"{'Updated' if model_name in unique_models else 'Added'} model card: "
                            f"{html_file} (organized: {is_organized})"
                        )
                else:
                    logger.debug(f"Skipping HTML file without metadata: {html_file}")

    # Extract final list of HTML files
    html_files = [path for path, _ in unique_models.values()]
    logger.info(f"Found {len(html_files)} unique model card HTML files")
    return html_files


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

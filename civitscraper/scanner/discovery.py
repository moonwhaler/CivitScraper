"""
File discovery for CivitScraper.

This module handles discovering model files in the configured directories.
"""

import bisect
import glob
import json
import logging
import os
import re
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

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
        # Escape the directory so names containing glob characters ([, ], *, ?)
        # are matched literally; only the configured pattern is a glob.
        escaped_dir = glob.escape(directory)
        if recursive:
            glob_pattern = os.path.join(escaped_dir, "**", pattern)
        else:
            glob_pattern = os.path.join(escaped_dir, pattern)

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


PREVIEW_EXTENSIONS = (".jpeg", ".jpg", ".png", ".webp", ".mp4")

# Sentinels used to turn a rendered preview filename back into a match pattern.
_INDEX_SENTINEL = "987654321"
_EXT_SENTINEL = ".civitscraperext"


# Directory listings shared by read-only bulk passes (gallery generation). Outside a
# ``cached_listings()`` scope every call lists the directory fresh, so code that writes
# or deletes previews never sees a stale view.
_listing_lock = threading.Lock()
_listing_depth = 0
_listing_cache: Dict[str, List[str]] = {}


@contextmanager
def cached_listings() -> Iterator[None]:
    """
    Cache sorted directory listings for the duration of a read-only bulk pass.

    Use only around code that does not create or delete files in the scanned
    directories (e.g. building the gallery from existing sidecars and previews).
    """
    global _listing_depth
    with _listing_lock:
        _listing_depth += 1
    try:
        yield
    finally:
        with _listing_lock:
            _listing_depth -= 1
            if _listing_depth == 0:
                _listing_cache.clear()


def _names_with_prefix(directory: str, prefix: str) -> List[str]:
    """Return directory entries starting with ``prefix`` (empty list if unreadable)."""
    with _listing_lock:
        caching = _listing_depth > 0
        names = _listing_cache.get(directory) if caching else None

    if names is None:
        try:
            listing = os.listdir(directory)
        except OSError:
            return []
        if not caching:
            return [name for name in listing if name.startswith(prefix)]
        names = sorted(listing)
        with _listing_lock:
            _listing_cache[directory] = names

    # Sorted listing: jump straight to the prefix instead of scanning every entry.
    start = bisect.bisect_left(names, prefix)
    result = []
    for name in names[start:]:
        if not name.startswith(prefix):
            break
        result.append(name)
    return result


def _norm(path: str) -> str:
    """Return an absolute, case-normalized path for comparisons."""
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def is_within(path: str, root: str) -> bool:
    """
    Check whether ``path`` is ``root`` or lies inside it.

    Uses real path-component containment (not string prefixes), so
    ``/models/loras2/x`` is *not* inside ``/models/loras``. Windows-safe.
    """
    norm_path = _norm(path)
    norm_root = _norm(root)
    try:
        return os.path.commonpath([norm_path, norm_root]) == norm_root
    except ValueError:
        # Different drives on Windows, or mixed absolute/relative paths
        return False


def has_metadata(file_path: str, config: Optional[Dict[str, Any]] = None) -> bool:
    """
    Check if file has metadata.

    Args:
        file_path: Path to file
        config: Configuration; when given, the configured metadata location
            (``output.base_dir``, ``output.metadata.path``/``filename``) is used.
            Without it, the legacy ``<model>.json`` next to the model is checked.

    Returns:
        True if file has metadata, False otherwise
    """
    if config is not None:
        metadata_path = get_metadata_path(file_path, config)
    else:
        metadata_path = os.path.splitext(file_path)[0] + ".json"

    return os.path.isfile(metadata_path)


def find_metadata_file(file_path: str, config: Dict[str, Any]) -> Optional[str]:
    """
    Find an existing metadata file for a model, honoring configured output locations.

    Falls back to the legacy ``<model>.json`` next to the model file.

    Args:
        file_path: Path to model file
        config: Configuration used to locate the metadata file

    Returns:
        Path to an existing metadata file, or None
    """
    candidates = [
        get_metadata_path(file_path, config),
        os.path.splitext(file_path)[0] + ".json",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def load_cached_metadata(file_path: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Load a model's metadata from its sidecar at the configured location.

    Args:
        file_path: Path to model file
        config: Configuration used to locate the metadata file

    Returns:
        Metadata dictionary, or None if missing or unreadable
    """
    metadata_path = get_metadata_path(file_path, config)
    if not os.path.isfile(metadata_path):
        return None

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
            return data
    except Exception as e:
        logger.error(f"Error loading cached metadata from {metadata_path}: {e}")
        return None


def _resolve_output_dir(
    file_path: str, config: Dict[str, Any], section_config: Dict[str, Any], model_type: str
) -> str:
    """
    Resolve the output directory for a model's metadata, HTML or images.

    ``output.base_dir`` takes precedence (``base_dir/{model_type}``); otherwise the
    section's ``path`` template is used (default ``{model_dir}``).
    """
    model_dir = os.path.dirname(file_path)
    model_name = os.path.splitext(os.path.basename(file_path))[0]

    base_dir = config.get("output", {}).get("base_dir")
    if base_dir:
        return os.path.join(os.path.expanduser(base_dir), model_type)

    path_template = section_config.get("path", "{model_dir}")
    path = path_template.replace("{model_dir}", model_dir)
    path = path.replace("{model_name}", model_name)
    path = path.replace("{model_type}", model_type)
    return str(path)


def _render_filename(template: str, file_path: str, model_type: str) -> str:
    """Render ``{model_name}``/``{model_type}`` placeholders in a filename template."""
    model_name = os.path.splitext(os.path.basename(file_path))[0]
    filename = template.replace("{model_name}", model_name)
    return filename.replace("{model_type}", model_type)


def get_metadata_path(file_path: str, config: Dict[str, Any]) -> str:
    """
    Get metadata file path for model file.

    Args:
        file_path: Path to model file
        config: Configuration

    Returns:
        Path to metadata file
    """
    output_config = config.get("output", {}).get("metadata", {})
    model_type = get_model_type(file_path, config)

    path = _resolve_output_dir(file_path, config, output_config, model_type)
    filename = _render_filename(
        output_config.get("filename", "{model_name}.json"), file_path, model_type
    )
    return str(os.path.join(path, filename))


def get_model_type(file_path: str, config: Dict[str, Any]) -> str:
    """
    Get model type for file.

    The input path that contains the file is found by real path containment;
    when input paths are nested, the most specific (longest) one wins.

    Args:
        file_path: Path to model file
        config: Configuration

    Returns:
        Model type
    """
    input_paths = config.get("input_paths", {})
    if not input_paths or not isinstance(input_paths, dict):
        return "Unknown"

    best_match_len = -1
    best_type = "Unknown"

    for path_config in input_paths.values():
        if not isinstance(path_config, dict):
            continue

        directory = path_config.get("path")
        if not directory or not isinstance(directory, str):
            continue

        if not is_within(file_path, directory):
            continue

        match_len = len(_norm(directory))
        if match_len > best_match_len:
            best_match_len = match_len
            model_type = path_config.get("type")
            best_type = model_type if isinstance(model_type, str) else "Unknown"

    return str(best_type)


def get_html_path(file_path: str, config: Dict[str, Any]) -> str:
    """
    Get HTML file path for model file.

    Args:
        file_path: Path to model file
        config: Configuration

    Returns:
        Path to HTML file
    """
    output_config = config.get("output", {}).get("metadata", {}).get("html", {})
    model_type = get_model_type(file_path, config)

    path = _resolve_output_dir(file_path, config, output_config, model_type)
    filename = _render_filename(
        output_config.get("filename", "{model_name}.html"), file_path, model_type
    )
    return str(os.path.join(path, filename))


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
    output_config = config.get("output", {}).get("images", {})

    # Split the image type into its base and index number ("preview12" -> "preview", "12")
    match = re.match(r"([a-zA-Z_]+)(\d*)", image_type)
    if match:
        base_image_type = match.group(1)
        index_number = match.group(2)
    else:
        base_image_type = image_type
        index_number = ""

    filename_template = output_config.get("filenames", {}).get(
        base_image_type, "{model_name}.{image_type}{ext}"
    )

    model_type = get_model_type(file_path, config)
    path = _resolve_output_dir(file_path, config, output_config, model_type)

    filename = _render_filename(filename_template, file_path, model_type)
    filename = filename.replace("{image_type}", base_image_type)
    filename = filename.replace("{ext}", ext)

    # Insert the index number before the extension
    if index_number:
        ext_pos = filename.rfind(ext)
        if ext_pos != -1:
            filename = filename[:ext_pos] + index_number + filename[ext_pos:]

    return str(os.path.join(path, filename))


def list_preview_files(file_path: str, config: Dict[str, Any]) -> List[Tuple[str, int, bool]]:
    """
    List a model's downloaded, numbered preview files.

    The match pattern is derived from the configured ``images.filenames.preview``
    template and output location, so custom templates, ``output.base_dir`` and
    file names containing glob characters (``[``, ``]``) all work. Files that do
    not follow the numbered naming scheme are ignored.

    Args:
        file_path: Path to model file
        config: Configuration

    Returns:
        List of ``(path, index, is_video)`` sorted by preview index
    """
    probe = get_image_path(file_path, config, f"preview{_INDEX_SENTINEL}", _EXT_SENTINEL)
    directory = os.path.dirname(probe)
    probe_name = os.path.basename(probe)

    if _INDEX_SENTINEL not in probe_name or not probe_name.endswith(_EXT_SENTINEL):
        logger.debug(f"Preview filename template has no index/extension slot: {probe_name}")
        return []

    stem = probe_name[: -len(_EXT_SENTINEL)]
    before, _, after = stem.rpartition(_INDEX_SENTINEL)
    ext_group = "|".join(re.escape(e[1:]) for e in PREVIEW_EXTENSIONS)
    pattern = re.compile(
        re.escape(before) + r"(\d+)" + re.escape(after) + r"\.(?i:(" + ext_group + r"))"
    )

    previews: List[Tuple[str, int, bool]] = []
    for name in _names_with_prefix(directory, before):
        match = pattern.fullmatch(name)
        if not match:
            continue
        full_path = os.path.join(directory, name)
        if not os.path.isfile(full_path):
            continue
        previews.append((full_path, int(match.group(1)), match.group(2).lower() == "mp4"))

    previews.sort(key=lambda item: item[1])
    return previews


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
        Model card HTML files (each once), organized locations first
    """
    # Get input paths
    input_paths = config.get("input_paths", {})

    # If no path IDs specified, use all
    if path_ids is None:
        path_ids = list(input_paths.keys())

    # Every model card once (normalized path). Same-named cards in different
    # folders are different models; the gallery's collapse_candidates merges
    # organized mirrors of one model and prefers the organized copy.
    html_files: List[str] = []
    seen = set()

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

        # With a central output directory, model cards live in base_dir/{type}
        base_dir = config.get("output", {}).get("base_dir")
        if base_dir:
            central_dir = os.path.join(
                os.path.expanduser(base_dir), str(path_config.get("type") or "Unknown")
            )
            if os.path.isdir(central_dir) and central_dir not in [
                d for d, _ in directories_to_scan
            ]:
                directories_to_scan.append((central_dir, False))

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

                if not os.path.isfile(metadata_path):
                    logger.debug(f"Skipping HTML file without metadata: {html_file}")
                    continue
                key = os.path.normcase(os.path.abspath(html_file))
                if key not in seen:
                    seen.add(key)
                    html_files.append(html_file)
                    logger.debug(f"Added model card: {html_file} (organized: {is_organized})")

    logger.info(f"Found {len(html_files)} unique model card HTML files")
    return html_files


def filter_files(
    files: List[str], skip_existing: bool = True, config: Optional[Dict[str, Any]] = None
) -> List[str]:
    """
    Filter files based on criteria.

    Args:
        files: List of file paths
        skip_existing: Whether to skip files that already have metadata
        config: Configuration used to locate metadata (see ``has_metadata``)

    Returns:
        Filtered list of file paths
    """
    filtered_files = []

    for file_path in files:
        if skip_existing and has_metadata(file_path, config):
            logger.debug(f"Skipping file with existing metadata: {file_path}")
            continue

        filtered_files.append(file_path)

    return filtered_files

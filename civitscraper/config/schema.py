"""
Known configuration keys, used to warn about typos.

An unknown key is ignored by the code that reads the configuration, so a typo
like ``skip_exisiting`` silently does nothing. ``find_unknown_keys`` reports
such keys with a "did you mean" suggestion. It never rejects a configuration.
"""

import difflib
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Schema values: LEAF = scalar or list value, FREE = anything below is accepted,
# a dict = known sub-keys, {MAP: schema} = user-chosen keys each matching schema.
LEAF = None
FREE = "*"
MAP = "<name>"

_API = {
    "key": LEAF,
    "base_url": LEAF,
    "timeout": LEAF,
    "max_retries": LEAF,
    "user_agent": LEAF,
    "domains": {"sfw": LEAF, "nsfw": LEAF},
    "nsfw": {"level_threshold": LEAF, "browsing_level": LEAF},
    "batch": {
        "enabled": LEAF,
        "max_concurrent": LEAF,
        "rate_limit": LEAF,
        "retry_delay": LEAF,
        "cache_size": LEAF,
        "download_rate_limit": LEAF,
        "download_workers": LEAF,
        "circuit_breaker": {"failure_threshold": LEAF, "reset_timeout": LEAF},
    },
}

_SCANNER = {
    "cache_dir": LEAF,
    "cache_validity": LEAF,
    "version_cache_validity": LEAF,
    "force_refresh": LEAF,
    "rehash": LEAF,
    "not_found_validity": LEAF,
    "hash_workers": LEAF,
}

_LOGGING = {
    "level": LEAF,
    "console": {"enabled": LEAF, "level": LEAF, "simple": LEAF},
    "file": {
        "enabled": LEAF,
        "level": LEAF,
        "directory": LEAF,
        "max_size": LEAF,
        "backup_count": LEAF,
    },
}

_OUTPUT = {
    "base_dir": LEAF,
    "metadata": {
        "format": LEAF,
        "path": LEAF,
        "filename": LEAF,
        "html": {
            "enabled": LEAF,
            "path": LEAF,
            "filename": LEAF,
            "skip_existing_html": LEAF,
            "generate_gallery": LEAF,
            "gallery_path": LEAF,
            "gallery_title": LEAF,
            "include_existing_in_gallery": LEAF,
        },
    },
    "images": {
        "save": LEAF,
        "path": LEAF,
        "max_count": LEAF,
        "filenames": FREE,
    },
}

_ORGANIZATION = {
    "enabled": LEAF,
    "template": LEAF,
    "custom_template": LEAF,
    "output_dir": LEAF,
    "operation_mode": LEAF,
    "on_collision": LEAF,
    # Legacy spellings of operation_mode, still honored by OrganizationConfig
    "move_files": LEAF,
    "create_symlinks": LEAF,
}

# Sections a job may override (merged over the global configuration)
_OVERRIDABLE: Dict[str, Any] = {
    "api": _API,
    "scanner": _SCANNER,
    "logging": _LOGGING,
    "output": _OUTPUT,
    "organization": _ORGANIZATION,
    "dry_run": LEAF,
}

_JOB: Dict[str, Any] = {
    "type": LEAF,
    "description": LEAF,
    "paths": LEAF,
    "recursive": LEAF,
    "skip_existing": LEAF,
    "verify_hashes": LEAF,
    "use_cached_metadata": LEAF,
    "force_refresh": LEAF,
    "loras_file": LEAF,
    "overwrite_triggers": LEAF,
    **_OVERRIDABLE,
}

SCHEMA: Dict[str, Any] = {
    "input_paths": {MAP: {"path": LEAF, "type": LEAF, "patterns": LEAF}},
    "default_job": LEAF,
    "jobs": {MAP: _JOB},
    "defaults": {"organization": {"operation_mode": LEAF, "on_collision": LEAF}},
    **_OVERRIDABLE,
}


def find_unknown_keys(config: Any, schema: Any = None, prefix: str = "") -> List[Tuple[str, str]]:
    """
    List configuration keys the schema does not know.

    Args:
        config: Configuration (or a part of it)
        schema: Schema for ``config``; defaults to the full ``SCHEMA``
        prefix: Dotted path of ``config`` (for messages)

    Returns:
        (dotted key path, suggestion or "") for every unknown key
    """
    if schema is None:
        schema = SCHEMA
    if schema is FREE or schema is LEAF or not isinstance(config, dict):
        return []

    unknown: List[Tuple[str, str]] = []
    if MAP in schema:
        for name, value in config.items():
            unknown.extend(find_unknown_keys(value, schema[MAP], f"{prefix}{name}."))
        return unknown

    for key, value in config.items():
        path = f"{prefix}{key}"
        if key not in schema:
            close = difflib.get_close_matches(str(key), list(schema), n=1, cutoff=0.7)
            unknown.append((path, close[0] if close else ""))
            continue
        unknown.extend(find_unknown_keys(value, schema[key], f"{path}."))
    return unknown


def warn_unknown_keys(config: Dict[str, Any]) -> int:
    """
    Log one warning per unknown configuration key.

    Args:
        config: Loaded configuration

    Returns:
        Number of unknown keys
    """
    unknown = find_unknown_keys(config)
    for path, suggestion in unknown:
        hint = f" (did you mean {suggestion}?)" if suggestion else ""
        logger.warning(f"Unknown config key {path}{hint}; it is ignored")
    return len(unknown)

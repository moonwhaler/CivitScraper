"""
Gallery data helpers for CivitScraper.

Turns the candidate files of a gallery (new model files plus existing model
cards) into one entry per card, detects duplicate copies of a model, and makes
the paths in the gallery data relative to the gallery so a moved or remounted
collection still links correctly.
"""

import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..scanner.discovery import get_metadata_path

logger = logging.getLogger(__name__)

# Reasons a scanned model file has no gallery card
UNMATCHED_NOT_ON_CIVITAI = "not_on_civitai"
UNMATCHED_NO_METADATA = "no_metadata"


def _model_file_of(path: str, builder: Any) -> Optional[str]:
    """Model file behind a gallery candidate (a model file or its HTML card)."""
    if path.lower().endswith(".html"):
        model_file: Optional[str] = builder._find_model_file(path)
        return model_file
    return path


def _version_id_of(path: str, builder: Any) -> Any:
    """Return the CivitAI version id from a candidate's sidecar, or None."""
    if path.lower().endswith(".html"):
        metadata_path = os.path.splitext(path)[0] + ".json"
    else:
        metadata_path = get_metadata_path(path, builder.config)
    metadata = builder._load_metadata(metadata_path)
    return metadata.get("id") if metadata else None


def collapse_candidates(paths: Iterable[str], builder: Any) -> List[Tuple[str, List[str]]]:
    """
    Pick one path per gallery card and find duplicate copies.

    Candidates sharing a filename are usually the same model seen twice: a model
    file and its HTML card, or an original and its organized copy/symlink. Those
    collapse into one card, preferring the organized path. Same-name files in
    different folders that are different CivitAI versions get a card each. The
    same version at two or more real locations (not organized mirrors) is a
    duplicate.

    Args:
        paths: Model files and HTML cards, in discovery order
        builder: ContextBuilder (for organization settings and sidecar lookup)

    Returns:
        (representative path, duplicate model file paths or []) per card
    """
    groups: Dict[str, List[str]] = {}
    seen = set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault(os.path.splitext(os.path.basename(path))[0], []).append(path)

    # Copy/symlink output mirrors an original that is listed anyway; in move mode
    # the organized file is the only copy.
    mirror_mode = builder.org_config.operation_mode in ("copy", "symlink")

    result: List[Tuple[str, List[str]]] = []
    for members in groups.values():
        if len(members) == 1:
            result.append((members[0], []))
            continue

        organized = {p: builder._is_organized(p) for p in members}

        def representative(candidates: List[str]) -> str:
            return next((p for p in candidates if organized[p]), candidates[0])

        def real_copies(candidates: List[str]) -> List[str]:
            copies: List[str] = []
            seen_real = set()
            for p in candidates:
                if mirror_mode and organized[p]:
                    continue
                model_file = _model_file_of(p, builder)
                if model_file is None:
                    continue
                real = os.path.normcase(os.path.realpath(model_file))
                if real not in seen_real:
                    seen_real.add(real)
                    copies.append(os.path.abspath(model_file))
            return copies

        if len(real_copies(members)) <= 1:
            # One model seen several times (file + card, original + mirror).
            result.append((representative(members), []))
            continue

        by_version: Dict[Any, List[str]] = {}
        for p in members:
            by_version.setdefault(_version_id_of(p, builder), []).append(p)
        for version_id, version_members in by_version.items():
            copies = real_copies(version_members)
            duplicates = copies if version_id is not None and len(copies) > 1 else []
            result.append((representative(version_members), duplicates))
    return result


def portable_path(path: Optional[str], gallery_dir: str, portable: bool = True) -> Optional[str]:
    """
    Express a local path relative to the gallery directory (forward slashes).

    URLs are returned unchanged. On Windows a path on another drive cannot be
    relative and stays absolute, as does every path when ``portable`` is off.

    Args:
        path: Local path or URL
        gallery_dir: Directory of the gallery HTML file
        portable: Use relative paths

    Returns:
        Relative or absolute path, or the input if it is empty or a URL
    """
    if not path or "://" in path or path.startswith("data:"):
        return path
    absolute = os.path.abspath(path)
    if not portable:
        return absolute
    try:
        relative = os.path.relpath(absolute, gallery_dir)
    except ValueError:
        return absolute
    return relative.replace(os.sep, "/")


def make_cards_portable(cards: List[Dict[str, Any]], gallery_dir: str, portable: bool) -> None:
    """Rewrite the local paths of merged gallery cards in place (see portable_path)."""
    for card in cards:
        for key in ("html_path", "preview_image_path", "file_path"):
            card[key] = portable_path(card.get(key), gallery_dir, portable)
        card["duplicates"] = [
            portable_path(p, gallery_dir, portable) for p in card.get("duplicates") or []
        ]
        for version in card.get("versions") or []:
            if version.get("is_local"):
                version["link"] = portable_path(version.get("link"), gallery_dir, portable)


# Version fields gallery.js reads; the rest only feeds the health flags.
_VERSION_KEYS_FOR_JS = ("name", "link", "is_local", "is_current")
# Card fields left out of models_data.js when empty (gallery.js treats missing as empty)
_OMIT_WHEN_EMPTY = ("duplicates", "health", "update_version", "removed")
# Card fields only the Python side needs (merging versions); gallery.js never reads them
_PYTHON_ONLY = ("model_id",)


def slim_cards_for_js(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Drop card data the gallery page does not read, to keep models_data.js small.

    Args:
        cards: Merged gallery cards

    Returns:
        New card dicts with trimmed version entries and empty optional fields removed
    """
    slim = []
    for card in cards:
        out = {
            k: v
            for k, v in card.items()
            if k not in _PYTHON_ONLY and not (k in _OMIT_WHEN_EMPTY and not v)
        }
        if "versions" in out:
            out["versions"] = [
                {k: v[k] for k in _VERSION_KEYS_FOR_JS if k in v} for v in out["versions"]
            ]
        slim.append(out)
    return slim


def unmatched_entries(
    unmatched: Iterable[Tuple[str, str]], gallery_dir: str, portable: bool
) -> List[Dict[str, Any]]:
    """
    Gallery entries for scanned model files that have no card.

    Args:
        unmatched: (model file path, reason) pairs; reason is
            UNMATCHED_NOT_ON_CIVITAI or UNMATCHED_NO_METADATA
        gallery_dir: Directory of the gallery HTML file
        portable: Use relative paths

    Returns:
        Sorted list of {name, folder, file_path, reason}
    """
    entries = [
        {
            "name": os.path.basename(path),
            "folder": os.path.basename(os.path.dirname(os.path.abspath(path))),
            "file_path": portable_path(path, gallery_dir, portable),
            "reason": reason,
        }
        for path, reason in unmatched
    ]
    entries.sort(key=lambda e: (str(e["reason"]), str(e["name"]).lower(), str(e["file_path"])))
    return entries

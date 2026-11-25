"""
Context preparation for HTML generation.

This module handles preparing context data for templates.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from ..api.domains import DEFAULT_DOMAINS, build_model_url, get_domain_settings, is_nsfw
from ..organization.config import OrganizationConfig
from ..organization.organizer import (
    is_in_organized_output,
    organized_output_root,
    original_dir_for,
)
from ..scanner.discovery import get_metadata_path, list_preview_files
from .images import ImageHandler
from .paths import PathManager
from .sanitizer import description_excerpt, sanitize_description

# Gallery card limits: the detail page shows everything, cards only need enough
# to search and copy (keeps models_data.js small for big collections).
MAX_CARD_TAGS = 20
MAX_CARD_TRIGGER_WORDS = 10
MAX_CARD_TRIGGER_CHARS = 300

HEALTH_UPDATE = "update"
HEALTH_NO_PREVIEW = "no_preview"
HEALTH_DUPLICATE = "duplicate"


def card_trigger_words(trained_words: Any) -> List[str]:
    """Trigger words for a gallery card: at most 10 entries and 300 characters."""
    if isinstance(trained_words, str):
        trained_words = [trained_words]
    if not isinstance(trained_words, list):
        return []
    words: List[str] = []
    total = 0
    for word in trained_words:
        word = str(word).strip().rstrip(",").strip() if word else ""
        if not word:
            continue
        if len(words) >= MAX_CARD_TRIGGER_WORDS or total + len(word) > MAX_CARD_TRIGGER_CHARS:
            break
        words.append(word)
        total += len(word)
    return words


def update_available(versions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Return the newest remote version that beats the local ones on its base model.

    A remote version counts only if it is newer than every local version on the same
    base model; returns None if there is no such version.

    Comparing per base model keeps e.g. a new SDXL release from flagging a model the
    user only has (and wants) for SD 1.5.
    """
    newest_local: Dict[Any, str] = {}
    for version in versions:
        if version.get("is_local"):
            base = version.get("base_model")
            created = version.get("created_at") or ""
            if created > newest_local.get(base, ""):
                newest_local[base] = created
            else:
                newest_local.setdefault(base, created)

    best: Optional[Dict[str, Any]] = None
    for version in versions:
        if version.get("is_local"):
            continue
        base = version.get("base_model")
        created = version.get("created_at") or ""
        if base not in newest_local or not created or created <= newest_local[base]:
            continue
        if best is None or created > (best.get("created_at") or ""):
            best = version
    return best


# Define a typed dictionary for the preview image result
class PreviewImageDict(TypedDict):
    """TypedDict representing a preview image with path and video flag."""

    path: str
    is_video: bool


# Type alias for the optional preview image result
PreviewImageResult = Optional[PreviewImageDict]

logger = logging.getLogger(__name__)


class VersionIndexCache:
    """
    Cache mapping a directory's local model versions, built once per directory.

    For each directory it records, per version ``id``: the local HTML path (a
    version is "local" when its ``.json`` sidecar is present, regardless of whether
    its HTML has been generated yet), the version's own metadata fields, and a
    deduplicated pool of every sibling version referenced by any local sidecar of
    the same model. This lets a detail page render the *union* of all versions of
    its model instead of just its own (possibly stale) snapshot.
    """

    def __init__(self):
        """Initialize the version index cache."""
        # dir -> {version_id -> html_path}
        self._html_paths: Dict[str, Dict[int, str]] = {}
        # dir -> model_id -> {version_id -> version dict (template fields)}
        self._versions_by_model: Dict[str, Dict[int, Dict[int, Dict[str, Any]]]] = {}

    def ensure_indexed(self, search_dir: str) -> None:
        """Build the index for a directory if not already cached."""
        if os.path.isdir(search_dir) and search_dir not in self._html_paths:
            self._build_index(search_dir)

    def get_html_path(self, search_dir: str, version_id: Optional[int]) -> Optional[str]:
        """
        Get the local HTML path for a version ID (sidecar presence = local).

        Args:
            search_dir: Directory to search in
            version_id: Version ID to find

        Returns:
            Absolute path to the HTML file if the version is local, else None
        """
        if not version_id or not os.path.isdir(search_dir):
            return None
        self.ensure_indexed(search_dir)
        return self._html_paths.get(search_dir, {}).get(version_id)

    def get_model_versions(
        self,
        search_dir: str,
        model_id: Optional[int],
        current_version_id: Optional[int],
        nsfw: bool = False,
        domains: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build the merged version list for a model from all local sidecars in a dir.

        Returns local versions (linked to their local HTML) plus remote-only
        versions (linked to CivitAI), deduped by version id, newest-first, each
        flagged with ``is_local`` and ``isCurrent`` (relative to current_version_id).
        Returns an empty list if no versions are known for the model.
        """
        if not model_id or not os.path.isdir(search_dir):
            return []
        domains = domains or DEFAULT_DOMAINS
        self.ensure_indexed(search_dir)

        pool = self._versions_by_model.get(search_dir, {}).get(model_id, {})
        if not pool:
            return []

        local_paths = self._html_paths.get(search_dir, {})
        result: List[Dict[str, Any]] = []
        for vid, version in pool.items():
            entry = dict(version)
            entry["isCurrent"] = vid == current_version_id
            if vid in local_paths:
                entry["is_local"] = True
                entry["link"] = local_paths[vid]
            else:
                entry["is_local"] = False
                entry["link"] = build_model_url(model_id, vid, nsfw, domains)
            result.append(entry)

        result.sort(key=lambda v: v.get("createdAt") or "", reverse=True)
        return result

    def _build_index(self, search_dir: str) -> None:
        """Build the html-path and per-model version-union index for a directory."""
        html_paths: Dict[int, str] = {}
        versions_by_model: Dict[int, Dict[int, Dict[str, Any]]] = {}

        def record_version(model_id: int, version: Dict[str, Any]) -> None:
            vid = version.get("id")
            if not vid:
                return
            model_versions = versions_by_model.setdefault(model_id, {})
            existing = model_versions.setdefault(vid, {})
            # Merge, preferring already-present non-empty fields (first writer wins
            # per field) so a richer remote sibling isn't overwritten by a sparse one.
            for key in ("name", "baseModel", "createdAt", "downloadCount"):
                if not existing.get(key) and version.get(key) is not None:
                    existing[key] = version.get(key)
            existing["id"] = vid

        try:
            for filename in os.listdir(search_dir):
                if not filename.endswith(".json"):
                    continue

                json_path = os.path.join(search_dir, filename)
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        metadata = json.load(f)
                except (json.JSONDecodeError, IOError):
                    continue

                vid = metadata.get("id")
                model_id = metadata.get("parentModel", {}).get("id") or metadata.get("modelId")
                if not vid or not model_id:
                    continue

                # Local version: sidecar present -> link to its (computed) HTML path.
                html_filename = os.path.splitext(filename)[0] + ".html"
                html_paths[vid] = os.path.abspath(os.path.join(search_dir, html_filename))

                # Seed the pool with this version's own metadata (downloadCount lives
                # under stats), so local-only versions still carry template fields.
                record_version(
                    model_id,
                    {
                        "id": vid,
                        "name": metadata.get("name"),
                        "baseModel": metadata.get("baseModel"),
                        "createdAt": metadata.get("createdAt"),
                        "downloadCount": metadata.get("stats", {}).get("downloadCount"),
                    },
                )
                # Merge every sibling this sidecar knows about into the model pool.
                for sibling in metadata.get("siblingVersions", []) or []:
                    record_version(model_id, sibling)
        except OSError as e:
            logger.debug(f"Error building version index for {search_dir}: {e}")

        self._html_paths[search_dir] = html_paths
        self._versions_by_model[search_dir] = versions_by_model
        logger.debug(f"Built version index for {search_dir}: {len(html_paths)} local versions")

    def invalidate(self, search_dir: Optional[str] = None) -> None:
        """
        Invalidate cached index.

        Args:
            search_dir: Directory to invalidate, or None for all
        """
        if search_dir:
            self._html_paths.pop(search_dir, None)
            self._versions_by_model.pop(search_dir, None)
        else:
            self._html_paths.clear()
            self._versions_by_model.clear()


# Global version index cache for reuse across context builders
_version_index_cache = VersionIndexCache()


def invalidate_version_index(search_dir: Optional[str] = None) -> None:
    """Invalidate the global version index cache (all dirs, or one)."""
    _version_index_cache.invalidate(search_dir)


def _relative_to(path: str, directory: str) -> str:
    """``path`` relative to ``directory`` with forward slashes; absolute on another drive."""
    absolute = os.path.abspath(path)
    try:
        return os.path.relpath(absolute, directory).replace(os.sep, "/")
    except ValueError:
        return absolute


class ContextBuilder:
    """Builder for template context."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize context builder.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.domains, self.nsfw_threshold, _ = get_domain_settings(config)
        self.path_manager = PathManager(config)
        self.image_handler = ImageHandler(config)
        self.org_config = OrganizationConfig.from_dict(config)

    def build_model_context(self, file_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build context for model template.

        Args:
            file_path: Path to model file
            metadata: Model metadata

            Returns:
            Template context
        """
        model_info = metadata.get("model") or {}
        parent = metadata.get("parentModel") or {}
        model_name = model_info.get("name", metadata.get("name", "Unknown"))
        model_type = model_info.get("type", "Unknown")
        # Version sidecars carry the creator on the parent model only.
        creator = (model_info.get("creator") or {}).get("username") or (
            parent.get("creator") or {}
        ).get("username")
        description = sanitize_description(metadata.get("description", ""))
        tags = model_info.get("tags") or parent.get("tags") or []
        stats = metadata.get("stats", {})
        image_paths = self.image_handler.get_image_paths(file_path, metadata)

        # Filter files to show only the current model's files and add local path info
        filtered_metadata = self._filter_model_files(file_path, metadata)

        # Build sibling versions context with local availability info
        # Get parent model ID for building CivitAI URLs
        parent_model_id = metadata.get("parentModel", {}).get("id") or metadata.get("modelId")
        model_nsfw = is_nsfw(metadata, self.nsfw_threshold)
        sibling_versions = self._build_sibling_versions_context(
            file_path,
            metadata.get("siblingVersions", []),
            parent_model_id,
            metadata.get("id"),
            model_nsfw,
        )

        # Calculate relative path to gallery
        html_path = self.path_manager.get_html_path(file_path)
        html_dir = os.path.dirname(os.path.abspath(html_path))

        # Get gallery path from config, default to index.html in model directory
        gallery_output_path = (
            self.config.get("output", {})
            .get("metadata", {})
            .get("html", {})
            .get("gallery_path", "index.html")
        )

        # Calculate relative path from model HTML to gallery
        gallery_path = "index.html"
        try:
            gallery_abs_path = os.path.abspath(gallery_output_path)
            gallery_path = os.path.relpath(gallery_abs_path, html_dir).replace(os.sep, "/")
        except ValueError:
            # On Windows, relpath can fail if paths are on different drives
            # Fall back to absolute path
            gallery_path = os.path.abspath(gallery_output_path)

        # Local version links are absolute; make them relative to this page.
        sibling_versions = [
            (
                dict(v, link=_relative_to(v["link"], html_dir))
                if v.get("is_local") and v.get("link")
                else v
            )
            for v in sibling_versions
        ]

        files = filtered_metadata.get("files") or []
        hashes = (files[0].get("hashes") or {}) if files else {}

        context = {
            "title": model_name,
            "model_name": model_name,
            "model_type": model_type,
            "creator": creator,
            "description": description,
            "tags": tags,
            "stats": stats,
            "images": image_paths,
            "metadata": filtered_metadata,
            "base_model": metadata.get("baseModel"),
            "version_name": metadata.get("name"),
            "hashes": {k: hashes[k] for k in ("AutoV2", "SHA256") if hashes.get(k)},
            "local_file_path": os.path.abspath(file_path),
            # Relative to the page, so copying still works after the collection moves.
            "file_rel_path": _relative_to(file_path, html_dir),
            "sibling_versions": sibling_versions,
            "parent_model": metadata.get("parentModel", {}),
            "gallery_path": gallery_path,
            "model_url": build_model_url(
                parent_model_id, metadata.get("id"), model_nsfw, self.domains
            ),
        }

        return context

    def build_gallery_context(
        self, file_paths: List[str], title: str, output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build context for gallery template.

        Args:
            file_paths: List of model file paths or HTML file paths
            title: Gallery title
            output_path: Path to output HTML file (for relative path calculation)

        Returns:
            Template context
        """
        context: Dict[str, Any] = {
            "title": title,
            "models": [],
            "output_path": output_path,
        }

        for file_path in file_paths:
            model_data = self._process_gallery_model(file_path, output_path)
            if model_data:
                context["models"].append(model_data)

        return context

    def _process_gallery_model(
        self, file_path: str, output_path: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Process a single model file for gallery context."""
        is_html_file = file_path.lower().endswith(".html")
        if is_html_file:
            # Model cards live next to their sidecar (default layout and base_dir)
            metadata_path = os.path.splitext(file_path)[0] + ".json"
        else:
            metadata_path = get_metadata_path(file_path, self.config)
        html_path = file_path if is_html_file else self.path_manager.get_html_path(file_path)

        metadata = self._load_metadata(metadata_path)
        if not metadata:
            return None

        output_dir = os.path.dirname(output_path) if output_path else os.path.dirname(file_path)
        # Use absolute path for the model's HTML file
        html_abs_path = os.path.abspath(html_path)

        preview_image = self._find_preview_image(file_path, metadata, output_dir, is_html_file)
        preview_data: Dict[str, Any] = {
            "path": preview_image["path"] if preview_image else None,
            "is_video": preview_image["is_video"] if preview_image else False,
        }

        stats = metadata.get("stats", {})
        model_stats = {
            "downloads": stats.get("downloadCount", 0),
            "rating": stats.get("rating", 0),
            "rating_count": stats.get("ratingCount", 0),
        }

        model_name = metadata.get("model", {}).get("name") or metadata.get("name", "Unknown")
        parent = metadata.get("parentModel") or {}
        model_info = metadata.get("model") or {}
        creator = (parent.get("creator") or {}).get("username") or (
            model_info.get("creator") or {}
        ).get("username")
        tags = parent.get("tags") or model_info.get("tags") or []

        parent_folder_path = os.path.dirname(file_path)
        folder_name = os.path.basename(parent_folder_path)
        # If the file_path itself is a directory (e.g. when scanning for .html
        # files in a dir) and that directory is the one we want (e.g.
        # "Character"), then basename gives an empty string.
        # In such cases, we might need to adjust. However, file_path for models is usually a file.
        # For robustness, if folder_name is empty and parent_folder_path is not the root,
        # it might indicate file_path was like 'Character/', so we take the
        # name before the trailing slash.
        if not folder_name and parent_folder_path and parent_folder_path != os.path.sep:
            folder_name = os.path.basename(os.path.normpath(parent_folder_path))

        # Count local versions (for filtering models with multiple local versions)
        local_version_count = self._count_local_versions(
            file_path, metadata.get("siblingVersions", [])
        )

        # Get file modification time from the actual model file
        file_modified = None
        model_file: Optional[str] = file_path
        if is_html_file:
            model_file = self._find_model_file(file_path)
            mtime_path = model_file if model_file else file_path
        else:
            mtime_path = file_path
        try:
            mtime = os.path.getmtime(mtime_path)
            file_modified = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            logger.debug(f"Could not get mtime for {mtime_path}")

        return {
            "name": model_name,
            "type": metadata.get("model", {}).get("type", "Unknown"),
            "base_model": metadata.get("baseModel", "Unknown"),
            # Plain-text excerpt only: the gallery searches it, the detail page shows
            # the full description. Keeps models_data.js small for big collections.
            "description": description_excerpt(metadata.get("description", "")),
            "html_path": html_abs_path,  # Use absolute path
            "preview_image_path": preview_data.get("path"),
            "is_video": preview_data.get("is_video", False),
            "stats": model_stats,
            "created_at": metadata.get("createdAt"),
            "updated_at": metadata.get("updatedAt"),
            "file_modified": file_modified,
            "version": metadata.get("name"),
            "folder_name": folder_name,
            "model_id": metadata.get("modelId"),
            "nsfw": is_nsfw(metadata, self.nsfw_threshold),
            "version_id": metadata.get("id"),
            "local_version_count": local_version_count,
            "creator": creator,
            "tags": [str(t) for t in tags if t][:MAX_CARD_TAGS],
            "trigger_words": card_trigger_words(metadata.get("trainedWords")),
            "file_path": os.path.abspath(model_file) if model_file else None,
            # Raw sibling versions for gallery merging (local + remote linking)
            "sibling_versions": metadata.get("siblingVersions", []),
        }

    @staticmethod
    def merge_gallery_models(
        models_data: List[Dict[str, Any]],
        domains: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Merge gallery cards so each CivitAI model is shown as a single card.

        Cards sharing the same ``model_id`` are collapsed into one
        representative card. The representative is the newest local version
        that has a preview image (falling back to the newest local version).
        A ``versions`` list is attached describing every version of the model:
        local versions (with links to their local HTML pages) and remote-only
        versions (with links to CivitAI).

        Cards without a ``model_id`` are never merged together; each is kept
        as its own standalone card.

        Args:
            models_data: Flat list of per-file gallery card dicts.

        Returns:
            Merged list with one card per model (plus standalone cards).
        """

        domains = domains or DEFAULT_DOMAINS

        def sort_key(value: Optional[str]) -> str:
            # None / missing dates sort last when ordering newest-first.
            return value or ""

        # Group cards by model_id. None model_id -> unique sentinel per card
        # so they never collapse together.
        groups: Dict[Any, List[Dict[str, Any]]] = {}
        order: List[Any] = []
        for index, card in enumerate(models_data):
            model_id = card.get("model_id")
            key = model_id if model_id is not None else ("__none__", index)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(card)

        merged: List[Dict[str, Any]] = []
        for key in order:
            members = groups[key]

            # Pick representative: newest member with a preview image,
            # falling back to the newest member overall.
            by_newest = sorted(members, key=lambda c: sort_key(c.get("created_at")), reverse=True)
            with_preview = [c for c in by_newest if c.get("preview_image_path")]
            representative = with_preview[0] if with_preview else by_newest[0]
            rep_version_id = representative.get("version_id")

            # Build version entries from the actual local member cards. The same
            # version at several local paths is one entry plus a duplicate list.
            member_ids = set()
            versions: List[Dict[str, Any]] = []
            copies: Dict[Any, List[str]] = {}
            for member in members:
                version_id = member.get("version_id")
                paths = member.get("duplicates") or (
                    [member["file_path"]] if member.get("file_path") else []
                )
                copies.setdefault(version_id, [])
                for path in paths:
                    if path not in copies[version_id]:
                        copies[version_id].append(path)
                if version_id in member_ids and version_id is not None:
                    continue
                member_ids.add(version_id)
                versions.append(
                    {
                        "name": member.get("version"),
                        "version_id": version_id,
                        "is_local": True,
                        "is_current": version_id == rep_version_id,
                        "link": member.get("html_path"),
                        "created_at": member.get("created_at"),
                        "base_model": member.get("base_model"),
                    }
                )

            # Add remote-only siblings (those without a local card), deduped.
            model_id = key if not isinstance(key, tuple) else None
            seen_remote = set()
            for member in members:
                for sibling in member.get("sibling_versions", []) or []:
                    sib_id = sibling.get("id")
                    if sib_id in member_ids or sib_id in seen_remote:
                        continue
                    seen_remote.add(sib_id)
                    versions.append(
                        {
                            "name": sibling.get("name"),
                            "version_id": sib_id,
                            "is_local": False,
                            "is_current": False,
                            "link": build_model_url(
                                model_id, sib_id, representative.get("nsfw", False), domains
                            ),
                            "created_at": sibling.get("createdAt"),
                            "base_model": sibling.get("baseModel"),
                        }
                    )

            # Sort versions newest-first.
            versions.sort(key=lambda v: sort_key(v.get("created_at")), reverse=True)

            merged_card = dict(representative)
            merged_card["versions"] = versions
            # Raw sibling lists are folded into "versions"; don't ship them twice.
            merged_card.pop("sibling_versions", None)

            duplicates = [paths for paths in copies.values() if len(paths) > 1]
            merged_card["duplicates"] = [p for paths in duplicates for p in paths]
            update = update_available(versions)
            merged_card["update_version"] = update.get("name") if update else None
            health = []
            if update:
                health.append(HEALTH_UPDATE)
            if not merged_card.get("preview_image_path"):
                health.append(HEALTH_NO_PREVIEW)
            if duplicates:
                health.append(HEALTH_DUPLICATE)
            merged_card["health"] = health
            merged.append(merged_card)

        return merged

    def _filter_model_files(self, file_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filter metadata to show only files relevant to the current model file.

        Args:
            file_path: Path to the current model file
            metadata: Original metadata

        Returns:
            Metadata with filtered files
        """
        # Create a copy of metadata to avoid modifying the original
        filtered_metadata = metadata.copy()

        current_filename = os.path.basename(file_path)
        current_name_no_ext = os.path.splitext(current_filename)[0]

        # Get all files from metadata
        all_files = metadata.get("files", [])
        if not all_files:
            return filtered_metadata

        # Try to find matching files
        matching_files = []

        for file_info in all_files:
            file_name = file_info.get("name", "")
            file_name_no_ext = os.path.splitext(file_name)[0]

            # Check if this file matches the current model file
            if (
                # Exact name match
                file_name == current_filename
                or
                # Name without extension match
                file_name_no_ext == current_name_no_ext
                or
                # Primary file flag (fallback)
                file_info.get("primary", False)
            ):
                # Add local file path information
                file_copy = file_info.copy()
                file_copy["local_path"] = os.path.abspath(file_path)
                file_copy["local_directory"] = os.path.dirname(os.path.abspath(file_path))
                matching_files.append(file_copy)

        # If no exact matches found, try to find the primary file or first file
        if not matching_files:
            for file_info in all_files:
                if file_info.get("primary", False):
                    file_copy = file_info.copy()
                    file_copy["local_path"] = os.path.abspath(file_path)
                    file_copy["local_directory"] = os.path.dirname(os.path.abspath(file_path))
                    matching_files.append(file_copy)
                    break

            # If still no match, use the first file as fallback
            if not matching_files and all_files:
                file_copy = all_files[0].copy()
                file_copy["local_path"] = os.path.abspath(file_path)
                file_copy["local_directory"] = os.path.dirname(os.path.abspath(file_path))
                matching_files.append(file_copy)

        # Update the metadata with filtered files
        filtered_metadata["files"] = matching_files

        logger.debug(
            f"Filtered {len(all_files)} files to {len(matching_files)} for {current_filename}"
        )

        return filtered_metadata

    def _count_local_versions(
        self, current_file_path: str, sibling_versions: List[Dict[str, Any]]
    ) -> int:
        """
        Count how many sibling versions have local HTML files.

        Uses the global version index cache for efficient lookups.

        Args:
            current_file_path: Path to the current model file
            sibling_versions: List of sibling version data from metadata

        Returns:
            Count of versions with local HTML files (including current)
        """
        if not sibling_versions:
            return 1  # At least the current version is local

        current_dir = self._sidecar_dir(current_file_path)
        count = 0

        for version in sibling_versions:
            version_id = version.get("id")
            if version_id and _version_index_cache.get_html_path(current_dir, version_id):
                count += 1

        return max(count, 1)  # At least 1 (the current version)

    def _build_sibling_versions_context(
        self,
        current_file_path: str,
        sibling_versions: List[Dict[str, Any]],
        parent_model_id: Optional[int] = None,
        current_version_id: Optional[int] = None,
        model_nsfw: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Build context for sibling versions, determining local availability.

        Uses the global version index cache for efficient lookups.

        Args:
            current_file_path: Path to the current model file
            sibling_versions: List of sibling version data from metadata
            parent_model_id: Parent model ID for building CivitAI URLs

        Returns:
            List of sibling version dicts with local availability info
        """
        current_dir = self._sidecar_dir(current_file_path)

        # Preferred path: union of every version of this model across all local
        # sidecars in the directory, so every version's detail page shows the same
        # complete list regardless of per-file snapshot drift.
        if parent_model_id:
            merged = _version_index_cache.get_model_versions(
                current_dir, parent_model_id, current_version_id, model_nsfw, self.domains
            )
            if merged:
                return merged

        # Fallback: no model id (or nothing indexed) -> use this file's own snapshot.
        if not sibling_versions:
            return []

        result = []
        for version in sibling_versions:
            version_data = version.copy()
            version_id = version.get("id")

            # Check if there's a local HTML file for this version (using cached index)
            local_html_path = _version_index_cache.get_html_path(current_dir, version_id)

            if local_html_path:
                version_data["is_local"] = True
                version_data["link"] = local_html_path
            else:
                version_data["is_local"] = False
                # Build CivitAI URL for remote versions, routing NSFW models to
                # civitai.red and SFW models to civitai.com.
                version_data["link"] = build_model_url(
                    parent_model_id, version_id, model_nsfw, self.domains
                )

            result.append(version_data)

        return result

    def _load_metadata(self, metadata_path: str) -> Optional[Dict[str, Any]]:
        """Load metadata from a JSON file, checking both organized and original locations."""
        # First try the direct path
        if os.path.isfile(metadata_path):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata: Dict[str, Any] = json.load(f)
                    return metadata
            except Exception as e:
                logger.error(f"Error loading metadata from {metadata_path}: {e}")
                return None

        # If metadata not found at direct path, try the matching original/organized
        # location derived from the organization settings.
        try:
            filename = os.path.basename(metadata_path)
            metadata_dir = os.path.dirname(os.path.abspath(metadata_path))
            candidates: List[str] = []

            if self._is_organized(metadata_path):
                original_dir = original_dir_for(metadata_dir, self.org_config, self.config)
                if original_dir:
                    candidates.append(os.path.join(original_dir, filename))
            else:
                found = self._find_in_organized_output(metadata_dir, filename)
                if found:
                    candidates.append(found)

            for candidate in candidates:
                if os.path.isfile(candidate):
                    try:
                        with open(candidate, "r", encoding="utf-8") as f:
                            alt_metadata: Dict[str, Any] = json.load(f)
                        logger.debug(f"Found metadata in alternative location: {candidate}")
                        return alt_metadata
                    except Exception as e:
                        logger.error(f"Error loading metadata from {candidate}: {e}")

        except Exception as e:
            logger.error(f"Error trying to find alternative metadata path for {metadata_path}: {e}")

        # If we got here, the metadata wasn't found in any location
        logger.warning(f"Metadata not found: {metadata_path}")
        return None

    def _find_preview_image(
        self, file_path: str, metadata: Dict[str, Any], output_dir: str, is_html_file: bool
    ) -> PreviewImageResult:
        """Find preview image for a model."""
        is_organized = self._is_organized(file_path)

        # If this is an HTML file in the original location, try to find its organized version first
        if is_html_file and not is_organized:
            organized_path = self._find_organized_version(file_path)
            if organized_path:
                organized_preview = self._try_standard_preview_path(
                    organized_path, output_dir, is_html_file
                )
                if organized_preview is not None:
                    return organized_preview

        preview_path = self._try_standard_preview_path(file_path, output_dir, is_html_file)
        if preview_path is not None:
            return preview_path

        # For HTML files, try additional locations
        if is_html_file:
            alt_preview_path = self._try_alternative_patterns(file_path, output_dir)
            if alt_preview_path is not None:
                return alt_preview_path

            dir_preview_path = self._try_images_directory(file_path, output_dir)
            if dir_preview_path is not None:
                return dir_preview_path

            metadata_preview_path = self._try_metadata_urls(metadata, file_path, output_dir)
            if metadata_preview_path is not None:
                return metadata_preview_path

        return None

    def _is_organized(self, path: str) -> bool:
        """Whether ``path`` lies inside the organization output."""
        return is_in_organized_output(path, self.org_config, self.config)

    def _find_in_organized_output(self, source_dir: str, filename: str) -> Optional[str]:
        """Search the organization output of ``source_dir`` for ``filename``."""
        organized_base = organized_output_root(source_dir, self.org_config)
        if not os.path.isdir(organized_base):
            return None
        for root, _, files in os.walk(organized_base):
            if filename in files:
                return os.path.join(root, filename)
        return None

    def _find_organized_version(self, file_path: str) -> Optional[str]:
        """Find the organized copy of a model card in its directory's organization output."""
        return self._find_in_organized_output(
            os.path.dirname(os.path.abspath(file_path)), os.path.basename(file_path)
        )

    def _sidecar_dir(self, file_path: str) -> str:
        """
        Directory holding a model's metadata sidecar (the version index directory).

        For model files this honors ``output.base_dir`` and custom metadata paths;
        HTML model cards always sit next to their sidecar.
        """
        if file_path.lower().endswith(".html"):
            return os.path.dirname(os.path.abspath(file_path))
        return os.path.dirname(os.path.abspath(get_metadata_path(file_path, self.config)))

    def _try_standard_preview_path(
        self, file_path: str, output_dir: str, is_html_file: bool
    ) -> PreviewImageResult:
        """Return the lowest-numbered downloaded preview for a model file or model card."""
        if is_html_file:
            model_file = self._find_model_file(file_path)
            if model_file:
                previews = list_preview_files(model_file, self.config)
            else:
                # No model file next to the card (e.g. base_dir): previews sit in
                # the card's directory, named after the card.
                html_dir = os.path.dirname(file_path)
                stem = os.path.splitext(os.path.basename(file_path))[0]
                output_cfg = self.config.get("output", {})
                local_cfg = dict(self.config)
                local_cfg["output"] = {
                    **output_cfg,
                    "base_dir": None,
                    "images": {**output_cfg.get("images", {}), "path": html_dir},
                }
                previews = list_preview_files(
                    os.path.join(html_dir, stem + ".safetensors"), local_cfg
                )
        else:
            previews = list_preview_files(file_path, self.config)

        if not previews:
            return None

        path, _, is_video = previews[0]
        result: PreviewImageDict = {"path": os.path.abspath(path), "is_video": is_video}
        return result

    def _find_model_file(self, html_file: str) -> Optional[str]:
        """Find corresponding model file for an HTML file."""
        html_dir = os.path.dirname(html_file)
        model_name = os.path.splitext(os.path.basename(html_file))[0]

        for ext in [".safetensors", ".ckpt", ".pt", ".bin"]:
            potential_path = os.path.join(html_dir, model_name + ext)
            if os.path.isfile(potential_path):
                return potential_path

        return None

    def _try_alternative_patterns(self, file_path: str, output_dir: str) -> PreviewImageResult:
        """Try alternative naming patterns for preview images."""
        html_dir = os.path.dirname(file_path)
        model_name = os.path.splitext(os.path.basename(file_path))[0]

        patterns = [
            f"{model_name}_preview",
            f"{model_name}.preview",
            f"{model_name}preview0",
            f"{model_name}-preview0",
            f"{model_name}_image0",
            f"{model_name}.image0",
        ]

        for pattern in patterns:
            for ext in [".jpeg", ".jpg", ".png", ".webp", ".mp4"]:
                preview_path = os.path.join(html_dir, pattern + ext)
                if os.path.isfile(preview_path):
                    is_video = ext.lower() == ".mp4"
                    result: PreviewImageDict = {
                        "path": os.path.abspath(preview_path),  # Use absolute path
                        "is_video": is_video,
                    }
                    return result

        return None

    def _try_images_directory(self, file_path: str, output_dir: str) -> PreviewImageResult:
        """Try finding preview image in images directory."""
        html_dir = os.path.dirname(file_path)
        model_name = os.path.splitext(os.path.basename(file_path))[0]
        images_dir = os.path.join(html_dir, "images")

        if os.path.isdir(images_dir):
            for filename in os.listdir(images_dir):
                if model_name.lower() in filename.lower():
                    preview_path = os.path.join(images_dir, filename)
                    is_video = filename.lower().endswith(".mp4")
                    result: PreviewImageDict = {
                        "path": os.path.abspath(preview_path),  # Use absolute path
                        "is_video": is_video,
                    }
                    return result

        return None

    def _try_metadata_urls(
        self, metadata: Dict[str, Any], file_path: str, output_dir: str
    ) -> PreviewImageResult:
        """Try using image URLs from metadata."""
        if not (
            "images" in metadata and isinstance(metadata["images"], list) and metadata["images"]
        ):
            return None

        for image in metadata["images"]:
            if "url" in image and image["url"]:
                preview_url = image["url"]
                is_video = preview_url.lower().endswith(".mp4")
                ext = ".mp4" if is_video else ".jpg"

                # Try to find local file using preview index pattern
                logger.debug(f"Searching for preview files with indices 0-4 for {file_path}")

                # Check both original and organized locations
                paths_to_check = [file_path]
                if not self._is_organized(file_path):
                    # If we're in the original location, also check organized
                    organized_path = self._find_organized_version(file_path)
                    if organized_path:
                        paths_to_check.append(organized_path)
                        logger.debug(f"Also checking organized path: {organized_path}")

                for check_path in paths_to_check:
                    # Try preview index pattern
                    for i in range(5):  # Check first 5 preview indices
                        preview_path = self.path_manager.get_image_path(
                            check_path, f"preview{i}", ext
                        )
                        logger.debug(f"Checking for local file ({i}): {preview_path}")

                        if os.path.isfile(preview_path):
                            logger.debug(f"Found local preview file: {preview_path}")
                            preview_result: PreviewImageDict = {
                                "path": os.path.abspath(preview_path),  # Use absolute path
                                "is_video": is_video,
                            }
                            return preview_result

                    # Try the original downloaded file name
                    image_filename = os.path.basename(preview_url)
                    local_path = os.path.join(os.path.dirname(check_path), image_filename)
                    logger.debug(f"Checking for original file: {local_path}")

                    if os.path.isfile(local_path):
                        logger.debug(f"Found original file: {local_path}")
                        original_result: PreviewImageDict = {
                            "path": os.path.abspath(local_path),  # Use absolute path
                            "is_video": is_video,
                        }
                        return original_result

                logger.debug("No local files found in original or organized locations")

                # Use remote URL as last resort
                logger.debug(f"No local file found, using remote URL: {preview_url}")
                logger.debug(f"Checking file_path directory: {os.path.dirname(file_path)}")

                # For CivitAI URLs, handle width parameter
                if preview_url and "image.civitai.com" in preview_url:
                    # Extract the width parameter if it exists
                    import re

                    width_match = re.search(r"width=(\d+)", preview_url)
                    width = width_match.group(1) if width_match else "450"

                    # Reconstruct URL based on file type
                    base_url = preview_url.split("width=")[0]
                    if is_video:
                        # For videos, only add width parameter
                        preview_url = f"{base_url}width={width}/" f"{os.path.basename(preview_url)}"
                    else:
                        # For images, include format=preview
                        preview_url = (
                            f"{base_url}format=preview/"
                            f"width={width}/"
                            f"{os.path.basename(preview_url)}"
                        )

                remote_result: PreviewImageDict = {"path": preview_url, "is_video": is_video}
                return remote_result

        return None

"""
Image manager for CivitScraper.

Downloads a model's preview images and keeps the preview files in step with the
sidecar's ``images`` list, where ``images[i]`` belongs to the file numbered
``i + 1`` (``<model>.preview3.jpeg``).

Preview files are never deleted. When CivitAI reorders a model's images, the
files are renamed to follow; images that are gone from CivitAI stay on disk as
*archived* previews (listed after the current ones, marked
``civitscraperArchived``); empty slots are filled by downloading.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..api.client import CivitAIClient
from ..utils.fs import atomic_write, move_no_clobber
from ..utils.imagesize import image_size
from .discovery import get_image_path, list_preview_files
from .sidecar import (
    NAMESPACE,
    SOURCE_FEED,
    bookkeeping,
    image_key,
    images_source,
)

logger = logging.getLogger(__name__)

ARCHIVED = "civitscraperArchived"
ORPHAN = "civitscraperOrphan"
_MOVE_SUFFIX = ".civitscraper-move"
_JOURNAL_SUFFIX = ".civitscraper-sync.json"


def _move_no_clobber(source: str, target: str) -> None:
    """Rename ``source`` to ``target``; never replaces an existing file."""
    move_no_clobber(source, target)


def _orphan() -> Dict[str, Any]:
    """Entry for a kept preview file whose image is unknown."""
    return {ARCHIVED: True, ORPHAN: True}


def _temp_name(path: str) -> str:
    """Hidden temporary name next to ``path`` (never matched as a preview)."""
    return os.path.join(os.path.dirname(path), f".{os.path.basename(path)}{_MOVE_SUFFIX}")


def _same_file_name(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


@dataclass
class _File:
    """An existing preview file: its number, path and trusted entry (None if unknown)."""

    index: int
    path: str
    entry: Optional[Dict[str, Any]]
    duplicate: bool = False


@dataclass
class SyncPlan:
    """What a preview sync will do: the new image list and the file moves."""

    images: List[Dict[str, Any]]
    moves: List[Tuple[str, str]] = field(default_factory=list)


class ImageManager:
    """
    Manager for model images.

    This class handles downloading and managing images for models.
    """

    def __init__(self, config: Dict[str, Any], api_client: CivitAIClient):
        """
        Initialize image manager.

        Args:
            config: Configuration dictionary
            api_client: CivitAI API client
        """
        self.config = config
        self.api_client = api_client
        self.output_config = config.get("output", {})
        self.dry_run = config.get("dry_run", False)

    # --- Paths ------------------------------------------------------------------

    def _preview_path(self, file_path: str, index: int, ext: str) -> str:
        return get_image_path(file_path, self.config, f"preview{index}", ext)

    def _journal_path(self, file_path: str) -> str:
        probe = self._preview_path(file_path, 1, ".jpeg")
        stem = os.path.splitext(os.path.basename(file_path))[0]
        return os.path.join(os.path.dirname(probe), f".{stem}{_JOURNAL_SUFFIX}")

    def _files_by_index(self, file_path: str) -> Dict[int, List[str]]:
        files: Dict[int, List[str]] = {}
        for path, index, _ in list_preview_files(file_path, self.config):
            files.setdefault(index, []).append(path)
        return files

    def _max_count(self, max_count: Optional[int]) -> Optional[int]:
        if max_count is None:
            max_count = self.output_config.get("images", {}).get("max_count")
        return int(max_count) if max_count is not None else None

    # --- Sync ---------------------------------------------------------------------

    def _trusted(self, path: str, entry: Optional[Dict[str, Any]], synced: bool) -> bool:
        """
        Whether a preview file shows the image ``entry`` describes.

        Once a sync has run, positions are trusted. Before that (older sidecars),
        the file's pixel size must match the entry; files whose size cannot be
        read (videos) are trusted.
        """
        if not isinstance(entry, dict) or entry.get(ORPHAN):
            return False
        if synced:
            return True
        width, height = entry.get("width"), entry.get("height")
        if not width or not height:
            return True
        size = image_size(path)
        return size is None or size == (width, height)

    def _best_match(
        self, paths: List[str], entry: Optional[Dict[str, Any]], synced: bool
    ) -> Optional[str]:
        """
        Return the file under one number that shows ``entry``'s image, if any.

        A file whose pixel size matches wins over one whose size cannot be read
        (a video), so a leftover ``.jpeg`` next to a ``.mp4`` is told apart.
        """
        if not isinstance(entry, dict) or entry.get(ORPHAN):
            return None
        size = (entry.get("width"), entry.get("height"))
        for path in paths:
            if all(size) and image_size(path) == size:
                return path
        for path in paths:
            if self._trusted(path, entry, synced):
                return path
        return None

    def plan_sync(
        self,
        file_path: str,
        old: Optional[Dict[str, Any]],
        fresh_images: List[Dict[str, Any]],
        fresh_source: str,
        max_count: Optional[int] = None,
        mirror: bool = False,
    ) -> SyncPlan:
        """
        Work out the new image list and the renames for a model's previews.

        Every existing preview file keeps a place in the new list: a trusted file
        under its image, any other file (unknown, a second file with the same
        number) as an archived orphan entry. Nothing is deleted.

        Showcase images (the version's own) are authoritative: current images take
        the first slots, files are renamed to follow, and images gone from CivitAI
        are archived after them. The NSFW feed is a changing selection, and copies
        or symlinks of organized models mirror other files: in those cases files
        keep their numbers and only empty slots get new images.

        Args:
            file_path: Model file
            old: Sidecar before the refresh (None for a new model)
            fresh_images: Images from CivitAI now
            fresh_source: SOURCE_SHOWCASE or SOURCE_FEED
            max_count: Preview limit (default: output.images.max_count)
            mirror: The model is an organized copy/symlink

        Returns:
            The plan (images list and moves)
        """
        cap = self._max_count(max_count)
        old_images = list((old or {}).get("images") or [])
        synced = bool(bookkeeping(old or {}).get("previewsSynced"))
        # A new model may find previews left by an earlier run: they are matched
        # against the fresh images (by pixel size) instead of an old list.
        reference = old_images if old is not None else list(fresh_images)

        files: List[_File] = []
        for index, paths in sorted(self._files_by_index(file_path).items()):
            entry = reference[index - 1] if index - 1 < len(reference) else None
            best = self._best_match(sorted(paths), entry, synced)
            first = best or sorted(paths)[0]
            matched = dict(entry) if best and isinstance(entry, dict) else None
            files.append(_File(index, first, matched))
            files.extend(
                _File(index, path, None, duplicate=True) for path in sorted(paths) if path != first
            )

        stable = mirror or SOURCE_FEED in (fresh_source, images_source(old or {}))
        if stable:
            return self._plan_fill_gaps(file_path, old_images, files, fresh_images, cap, mirror)
        return self._plan_reorder(file_path, files, fresh_images, cap)

    def _plan_reorder(
        self,
        file_path: str,
        files: List["_File"],
        fresh_images: List[Dict[str, Any]],
        cap: Optional[int],
    ) -> SyncPlan:
        current = list(fresh_images if cap is None else fresh_images[:cap])
        fresh_by_key = {image_key(i): i for i in fresh_images if image_key(i)}
        slot_of = {image_key(img): n for n, img in enumerate(current) if image_key(img)}

        placed: Dict[int, str] = {}  # target slot (0-based) -> file
        kept: List[Tuple[str, Dict[str, Any]]] = []
        for f in files:
            key = image_key(f.entry) if f.entry else ""
            slot = slot_of.get(key) if key else None
            if slot is not None and slot not in placed:
                placed[slot] = f.path
            elif f.entry is None:
                kept.append((f.path, _orphan()))
            elif key in fresh_by_key:
                kept.append((f.path, dict(fresh_by_key[key])))  # on CivitAI, past the cap
            else:
                kept.append((f.path, {**f.entry, ARCHIVED: True}))

        images = [dict(i) for i in current] + [entry for _, entry in kept]
        targets = list(placed.items()) + [(len(current) + n, p) for n, (p, _) in enumerate(kept)]
        moves = []
        for slot, path in targets:
            target = self._preview_path(file_path, slot + 1, os.path.splitext(path)[1])
            if not _same_file_name(target, path):
                moves.append((path, target))
        return SyncPlan(images, moves)

    def _plan_fill_gaps(
        self,
        file_path: str,
        old_images: List[Dict[str, Any]],
        files: List["_File"],
        fresh_images: List[Dict[str, Any]],
        cap: Optional[int],
        mirror: bool,
    ) -> SyncPlan:
        """Keep every file at its number; put fresh images into empty slots only."""
        images = [dict(i) if isinstance(i, dict) else _orphan() for i in old_images]
        used = set()
        duplicates = []
        for f in files:
            if f.duplicate:
                duplicates.append(f.path)
                continue
            while len(images) < f.index:
                images.append(_orphan())
            if f.entry is None:
                images[f.index - 1] = _orphan()  # unknown file under this number
            used.add(f.index)

        moves: List[Tuple[str, str]] = []
        if not mirror:  # a second file with the same number gets its own number
            for path in duplicates:
                images.append(_orphan())
                moves.append(
                    (path, self._preview_path(file_path, len(images), os.path.splitext(path)[1]))
                )
                used.add(len(images))

        shown = {image_key(images[i - 1]) for i in used}
        candidates = [dict(i) for i in fresh_images if image_key(i) and image_key(i) not in shown]
        slot = current = 0
        while candidates and (cap is None or current < cap):
            if slot >= len(images):
                images.append(candidates.pop(0))
            elif images[slot].get(ARCHIVED):
                slot += 1
                continue
            elif slot + 1 not in used:
                images[slot] = candidates.pop(0)
            current += 1
            slot += 1
        return SyncPlan(images, moves)

    def recover_sync(self, file_path: str) -> Optional[List[Dict[str, Any]]]:
        """
        Finish a preview sync that was interrupted (crash between renames and save).

        Returns:
            The image list the sync was going to save, or None if nothing was pending
        """
        journal_path = self._journal_path(file_path)
        try:
            with open(journal_path, "r", encoding="utf-8") as f:
                journal = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            logger.warning(f"Ignoring unreadable preview sync journal {journal_path}: {e}")
            return None
        for source, temp, target in journal.get("moves", []):
            if journal.get("phase") == 1 and os.path.lexists(source) and not os.path.lexists(temp):
                _move_no_clobber(source, temp)
        for _source, temp, target in journal.get("moves", []):
            if os.path.lexists(temp) and not os.path.lexists(target):
                _move_no_clobber(temp, target)
            elif os.path.lexists(temp):
                logger.warning(f"Preview sync left {temp}: {target} exists; nothing was moved")
        logger.info(f"Finished an interrupted preview sync for {file_path}")
        images = journal.get("images")
        return images if isinstance(images, list) else None

    def apply_sync(self, file_path: str, plan: SyncPlan) -> bool:
        """
        Rename preview files as planned (no-clobber, journaled).

        The journal stays until ``finish_sync``, called once the sidecar with the
        new image list is saved; ``recover_sync`` completes an interrupted run.

        Returns:
            True if every rename happened (or none were needed)
        """
        if not plan.moves:
            return True
        if self.dry_run:
            logger.info(f"Dry run: would renumber {len(plan.moves)} previews of {file_path}")
            return False
        moves = [(src, _temp_name(src), dst) for src, dst in plan.moves]
        journal_path = self._journal_path(file_path)
        journal = {"moves": moves, "images": plan.images, "phase": 1}
        try:
            atomic_write(journal_path, json.dumps(journal))
            for src, temp, _ in moves:
                _move_no_clobber(src, temp)
            journal["phase"] = 2
            atomic_write(journal_path, json.dumps(journal))
            for _, temp, dst in moves:
                _move_no_clobber(temp, dst)
        except OSError as e:
            # Nothing is lost: files sit under their old or temporary names, and
            # the journal lets the next run finish the renames.
            logger.error(f"Could not renumber previews of {file_path} ({e}); retried next run")
            return False
        logger.debug(f"Renumbered {len(moves)} previews of {file_path}")
        return True

    def finish_sync(self, file_path: str) -> None:
        """Drop the journal of a completed sync (the sidecar is saved)."""
        try:
            os.remove(self._journal_path(file_path))
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Could not remove preview sync journal of {file_path}: {e}")

    def sync_previews(
        self,
        file_path: str,
        old: Optional[Dict[str, Any]],
        metadata: Dict[str, Any],
        fresh_source: str,
        mirror: bool = False,
    ) -> Dict[str, Any]:
        """
        Bring a model's preview files in step with freshly fetched images.

        Plans the new image list, renames the files and returns the metadata to
        save, with ``images`` set to the new list. Call ``finish_sync`` after
        saving it.

        Args:
            file_path: Model file
            old: Sidecar before the refresh (None for a new model)
            metadata: Merged metadata to save (its images are CivitAI's current ones)
            fresh_source: SOURCE_SHOWCASE or SOURCE_FEED
            mirror: The model is an organized copy/symlink

        Returns:
            The metadata with the synced image list
        """
        if self.dry_run:
            return metadata
        pending = self.recover_sync(file_path)
        if pending is not None:
            # The files now follow the list the interrupted sync was saving.
            old = {
                **(old or {}),
                "images": pending,
                NAMESPACE: {**bookkeeping(old or {}), "previewsSynced": True},
            }
        plan = self.plan_sync(
            file_path, old, list(metadata.get("images") or []), fresh_source, mirror=mirror
        )
        if not self.apply_sync(file_path, plan):
            # Keep the list the files still follow; the journal finishes next run.
            return {**metadata, "images": list((old or {}).get("images") or [])}
        result = dict(metadata)
        result["images"] = plan.images
        result[NAMESPACE] = {**bookkeeping(metadata), "previewsSynced": True}
        return result

    # --- Downloads ----------------------------------------------------------------

    def download_images(
        self,
        file_path: str,
        metadata: Dict[str, Any],
        max_count: Optional[int] = None,
        force_refresh: bool = False,
    ) -> List[str]:
        """
        Download the current images whose preview slot is empty.

        Existing preview files are never replaced or removed (to fetch one again,
        delete it). Archived entries are not downloaded.

        Args:
            file_path: Path to model file
            metadata: Model metadata
            max_count: Maximum number of current images (default: output.images.max_count)
            force_refresh: Kept for callers; existing previews are still kept

        Returns:
            Local paths of the model's previews (existing and newly downloaded)
        """
        cap = self._max_count(max_count)
        images = metadata.get("images") or []
        present = self._files_by_index(file_path)

        wanted: List[Tuple[int, Dict[str, Any]]] = []
        current = 0
        for i, image in enumerate(images):
            if not isinstance(image, dict) or image.get(ARCHIVED):
                continue
            if cap is not None and current >= cap:
                break
            current += 1
            if (i + 1) not in present:
                wanted.append((i, image))

        for n, (i, image) in enumerate(wanted, 1):
            path = self._download_single_image(file_path, image, i, len(wanted))
            if path:
                present.setdefault(i + 1, []).append(path)
        return [paths[0] for _, paths in sorted(present.items())]

    def _existing_preview_paths(self, file_path: str, max_count: Optional[int]) -> List[str]:
        """
        Paths of a model's numbered preview files, lowest number first.

        Args:
            file_path: Path to model file
            max_count: Maximum number of images

        Returns:
            Preview file paths
        """
        paths = [path for path, _, _ in list_preview_files(file_path, self.config)]
        return paths[:max_count] if max_count is not None else paths

    def _download_single_image(
        self, file_path: str, image: Dict[str, Any], index: int, total_count: int
    ) -> Optional[str]:
        """
        Download one image into its (empty) preview slot.

        Args:
            file_path: Path to model file
            image: Image data
            index: Image index (0-based; the file is numbered index + 1)
            total_count: Number of images being downloaded (for log messages)

        Returns:
            Local path of the preview, or None if the download failed
        """
        image_url = image.get("url")
        if not image_url:
            return None
        ext = os.path.splitext(image_url)[1]
        image_path = self._preview_path(file_path, index + 1, ext)
        if os.path.lexists(image_path):
            return image_path
        if self.dry_run:
            logger.info(f"Dry run: Would download image {index + 1} to {image_path}")
            return image_path
        return self._perform_download(image_url, image_path, index, total_count)

    def _perform_download(
        self, image_url: str, image_path: str, index: int, total_count: int
    ) -> Optional[str]:
        """
        Perform the actual download of an image.

        Args:
            image_url: URL of the image
            image_path: Path to save the image
            index: Image index
            total_count: Total number of images to download

        Returns:
            Local path of the downloaded file (``.mp4`` for videos), or None on failure
        """
        os.makedirs(os.path.dirname(image_path), exist_ok=True)

        preview_index = index + 1
        logger.debug(f"Downloading image {preview_index}/{total_count}")
        success, content_type = self.api_client.download_image(image_url, image_path)

        if not success:
            logger.warning(f"Failed to download image {preview_index}/{total_count}")
            return None

        # A video served under an image URL is renamed to .mp4 (the pages look for it)
        is_video = bool(content_type and content_type.startswith("video/"))
        if is_video and not image_path.lower().endswith(".mp4"):
            new_path = os.path.splitext(image_path)[0] + ".mp4"
            try:
                _move_no_clobber(image_path, new_path)
                logger.info(
                    f"Renamed video file from {image_path} to {new_path} "
                    f"based on Content-Type: {content_type}"
                )
                image_path = new_path
            except OSError as e:
                logger.warning(f"Kept video under {image_path}: cannot rename to {new_path} ({e})")

        return image_path

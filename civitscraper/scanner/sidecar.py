"""
Sidecar bookkeeping for CivitScraper.

A model's metadata sidecar (``<model>.json``) holds CivitAI's data plus keys other
tools write (Forge's Lora editor adds "activation text", "preferred weight",
"notes", ...). CivitScraper keeps its own bookkeeping under one key,
``"civitscraper"``:

``fetchedAt``
    When CivitAI's data was last fetched successfully (epoch seconds).
``checkedAt``
    When CivitAI last gave a definite answer about the model (data, 404 or
    another 4xx). Refreshes are scheduled by it.
``imagesSource``
    Where ``images`` came from: ``"showcase"`` (the version's own images) or
    ``"feed"`` (the NSFW image feed, a changing community selection).
``previewsSynced``
    The preview files follow ``images`` by position (``images[i]`` is preview
    ``i + 1``); set once a preview sync has run.
``removed``
    ``{"what": "version" | "model", "at": ts}`` while CivitAI answers 404. The
    local data is kept unchanged.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

NAMESPACE = "civitscraper"
# Transient in-memory marker telling save_metadata to bypass skip_existing.
# Popped before serialization; never written to disk.
DIRTY_FLAG = "_civitscraper_dirty"
# Transient marker set by MetadataManager.complete_images: where the fresh images
# came from and whether they are a degraded stand-in (the NSFW feed failed).
IMAGES_INFO = "_civitscraper_images"

SOURCE_SHOWCASE = "showcase"
SOURCE_FEED = "feed"


def has_civitai_metadata(metadata: Any) -> bool:
    """Whether a sidecar holds CivitAI data (Forge writes sidecars without it)."""
    return isinstance(metadata, dict) and bool(metadata.get("id")) and bool(
        metadata.get("modelId")
    )


def load_sidecar(path: str) -> Optional[Dict[str, Any]]:
    """Read a sidecar; None if it is missing, unreadable or not a JSON object."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def bookkeeping(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Return CivitScraper's own keys of a sidecar (empty for older sidecars)."""
    value = metadata.get(NAMESPACE)
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def last_fetched(metadata: Dict[str, Any], sidecar_path: Optional[str] = None) -> float:
    """
    When CivitAI's data for this sidecar was last fetched.

    Falls back to the older ``siblingVersionsFetchedAt`` stamp, then to the sidecar
    file's modification time, then 0 (never).
    """
    for value in (bookkeeping(metadata).get("fetchedAt"), metadata.get("siblingVersionsFetchedAt")):
        number = _number(value)
        if number is not None:
            return number
    if sidecar_path:
        try:
            return os.path.getmtime(sidecar_path)
        except OSError:
            pass
    return 0.0


def last_checked(metadata: Dict[str, Any], sidecar_path: Optional[str] = None) -> float:
    """When CivitAI last answered for this sidecar (see ``checkedAt``)."""
    number = _number(bookkeeping(metadata).get("checkedAt"))
    return number if number is not None else last_fetched(metadata, sidecar_path)


def image_key(image: Any) -> str:
    """
    Identity of a CivitAI image, stable across refreshes.

    CivitAI image URLs look like ``https://image.civitai.com/<key>/<uuid>/...``;
    the UUID identifies the image. Other URLs are used whole, without the query.
    """
    if not isinstance(image, dict):
        return ""
    url = str(image.get("url") or "")
    if not url:
        return ""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.hostname and parsed.hostname.endswith("civitai.com") and len(parts) >= 2:
        return parts[1]
    return f"{parsed.netloc}{parsed.path}" or url


def images_source(metadata: Dict[str, Any]) -> str:
    """
    Where a sidecar's images came from.

    Older sidecars carry no tag: entries from the NSFW feed have an ``id``,
    showcase entries do not.
    """
    tagged = bookkeeping(metadata).get("imagesSource")
    if tagged in (SOURCE_SHOWCASE, SOURCE_FEED):
        return str(tagged)
    images = metadata.get("images") or []
    if any(isinstance(i, dict) and i.get("id") is not None for i in images):
        return SOURCE_FEED
    return SOURCE_SHOWCASE


def _with_bookkeeping(metadata: Dict[str, Any], **changes: Any) -> Dict[str, Any]:
    result = dict(metadata)
    keys = dict(bookkeeping(metadata))
    for key, value in changes.items():
        if value is None:
            keys.pop(key, None)
        else:
            keys[key] = value
    result[NAMESPACE] = keys
    result[DIRTY_FLAG] = True
    return result


def merge_refreshed(
    old: Optional[Dict[str, Any]], fresh: Dict[str, Any], now: Optional[float] = None
) -> Dict[str, Any]:
    """
    Combine a sidecar with freshly fetched CivitAI data.

    Every key CivitAI sent replaces the old value; every other key (Forge's, the
    user's, parentModel/siblingVersions from enrichment) is kept. When the fresh
    images are a degraded stand-in (the NSFW feed failed) or came back empty while
    the sidecar had images, the old images are kept.

    Args:
        old: Existing sidecar, or None for a new model
        fresh: Fresh CivitAI data (may carry the IMAGES_INFO marker, consumed here)
        now: Timestamp to record (default: now)

    Returns:
        The merged sidecar, marked dirty so it is written
    """
    now = time.time() if now is None else now
    old = old or {}
    fresh = dict(fresh)
    info = fresh.pop(IMAGES_INFO, None) or {}
    fresh.pop(NAMESPACE, None)
    fresh.pop(DIRTY_FLAG, None)

    merged = dict(old)
    merged.update(fresh)

    old_images = old.get("images") or []
    degraded = bool(info.get("degraded")) or not fresh.get("images")
    if degraded and old_images:
        merged["images"] = old_images
        source = images_source(old)
    else:
        source = info.get("source") or images_source(fresh)

    return _with_bookkeeping(
        merged, fetchedAt=now, checkedAt=now, imagesSource=source, removed=None
    )


def mark_removed(old: Dict[str, Any], what: str, now: Optional[float] = None) -> Dict[str, Any]:
    """
    Record that CivitAI answered 404 for a version or its whole model.

    Nothing else changes. The first date is kept; a later "model" answer
    widens an earlier "version" one.
    """
    now = time.time() if now is None else now
    previous = bookkeeping(old).get("removed")
    removed = dict(previous) if isinstance(previous, dict) else {"at": now}
    if what == "model" or "what" not in removed:
        removed["what"] = what
    return _with_bookkeeping(old, removed=removed, checkedAt=now)


def mark_checked(old: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    """Record a definite answer without data (e.g. 401/403 for early access)."""
    now = time.time() if now is None else now
    return _with_bookkeeping(old, checkedAt=now)


def removed_info(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the ``removed`` record of a sidecar, or None."""
    value = bookkeeping(metadata).get("removed")
    return value if isinstance(value, dict) else None


def current_images(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the sidecar's images that are still on CivitAI (not archived)."""
    return [
        i
        for i in metadata.get("images") or []
        if isinstance(i, dict) and not i.get("civitscraperArchived")
    ]

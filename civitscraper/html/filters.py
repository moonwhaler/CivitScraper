"""
Jinja filters for the HTML templates.

Small, pure formatting helpers so templates show sizes, counts and dates the
same way everywhere.
"""

import re
from typing import Any

from jinja2 import Undefined

# Model types with their own colour code in the theme; everything else is "other".
_TYPE_SLUGS = {
    "lora": "lora",
    "locon": "locon",
    "lycoris": "locon",
    "dora": "lora",
    "checkpoint": "checkpoint",
    "textualinversion": "embedding",
    "embedding": "embedding",
    "vae": "vae",
    "controlnet": "controlnet",
}


def _plain(value: Any) -> Any:
    """Treat a Jinja ``Undefined`` (a missing sidecar field) like None."""
    return None if isinstance(value, Undefined) else value


def filesize(kb: Any) -> str:
    """Format a size in kilobytes (CivitAI's ``sizeKB``) as KB, MB or GB."""
    kb = _plain(kb)
    try:
        value = float(kb)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    for unit in ("KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "KB" else f"{value:.1f} {unit}"
        value /= 1024
    return ""  # pragma: no cover


def compact(number: Any) -> str:
    """Format a count compactly: 950, 12.3k, 4.1M."""
    number = _plain(number)
    try:
        value = float(number)
    except (TypeError, ValueError):
        return ""
    for limit, suffix in ((1e6, "M"), (1e3, "k")):
        if abs(value) >= limit:
            text = f"{value / limit:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return f"{value:.0f}"


def date(iso: Any) -> str:
    """Return the YYYY-MM-DD part of an ISO timestamp (empty for anything else)."""
    match = re.match(r"\d{4}-\d{2}-\d{2}", str(_plain(iso) or ""))
    return match.group(0) if match else ""


def type_slug(model_type: Any) -> str:
    """CSS slug for a model type's colour code (lora, locon, checkpoint, ... or other)."""
    key = re.sub(r"[^a-z]", "", str(_plain(model_type) or "").lower())
    return _TYPE_SLUGS.get(key, "other")


def version_label(name: Any) -> str:
    """Version name as shown in stamps: "1.0" becomes "v1.0"; names are kept as they are."""
    text = str(_plain(name) or "").strip()
    if re.fullmatch(r"\d+(\.\d+)*", text):
        return f"v{text}"
    return text


FILTERS = {
    "filesize": filesize,
    "compact": compact,
    "date": date,
    "type_slug": type_slug,
    "version_label": version_label,
}

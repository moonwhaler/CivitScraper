"""NSFW classification and civitai.com / civitai.red domain routing.

Since 2026-04-15 CivitAI serves SFW models on civitai.com and NSFW models on
civitai.red. This module is the single source of truth for deciding whether a
model is NSFW and which public domain its pages live on. Pure functions only —
no I/O, no network.
"""

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_DOMAINS: Dict[str, str] = {"sfw": "civitai.com", "nsfw": "civitai.red"}
DEFAULT_LEVEL_THRESHOLD: int = 4  # Mature/R and above
DEFAULT_BROWSING_LEVEL: str = "X"  # /images nsfw enum for NSFW models


def get_domain_settings(config: Dict[str, Any]) -> Tuple[Dict[str, str], int, str]:
    """Resolve domain/NSFW settings from config, filling defaults."""
    api = config.get("api", {}) if isinstance(config, dict) else {}
    domains = dict(DEFAULT_DOMAINS)
    domains.update(api.get("domains", {}) or {})
    nsfw_cfg = api.get("nsfw", {}) or {}
    threshold = nsfw_cfg.get("level_threshold", DEFAULT_LEVEL_THRESHOLD)
    browsing_level = nsfw_cfg.get("browsing_level", DEFAULT_BROWSING_LEVEL)
    return domains, threshold, browsing_level


def is_nsfw(metadata: Dict[str, Any], level_threshold: int = DEFAULT_LEVEL_THRESHOLD) -> bool:
    """True when the model/version is NSFW.

    NSFW if the version ``nsfwLevel >= level_threshold``, or a truthy ``nsfw`` flag
    is present. Real by-hash responses put ``nsfwLevel`` at the top level (verified)
    and the boolean ``nsfw`` flag under ``metadata["model"]["nsfw"]`` (the top-level
    ``nsfw`` is typically null), so both locations are checked.
    """
    if metadata.get("nsfw"):
        return True
    if isinstance(metadata.get("model"), dict) and metadata["model"].get("nsfw"):
        return True
    level = metadata.get("nsfwLevel")
    if isinstance(level, (int, float)):
        return level >= level_threshold
    return False


def model_page_domain(nsfw: bool, domains: Dict[str, str]) -> str:
    """Return the public domain for a model page."""
    return domains["nsfw"] if nsfw else domains["sfw"]


def build_model_url(
    model_id: Optional[Any],
    version_id: Optional[Any],
    nsfw: bool,
    domains: Dict[str, str],
) -> str:
    """Build a model-page URL on the correct domain.

    Mirrors the two branches previously hardcoded in context.py: with a model id
    the path is ``/models/{model_id}?modelVersionId={version_id}``; without one it
    is ``/models?modelVersionId={version_id}``.
    """
    domain = model_page_domain(nsfw, domains)
    if model_id:
        return f"https://{domain}/models/{model_id}?modelVersionId={version_id}"
    return f"https://{domain}/models?modelVersionId={version_id}"

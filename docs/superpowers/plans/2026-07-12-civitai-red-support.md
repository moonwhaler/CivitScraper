# civitai.red Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CivitScraper fetch NSFW images/videos for NSFW models and emit model-page links that resolve on `civitai.red`, choosing the domain automatically per model.

**Architecture:** A new pure-function module (`api/domains.py`) centralizes NSFW detection and domain/URL selection. NSFW models pull previews from the `/images` endpoint with an `nsfw` browsing-level parameter (the current inline by-hash images are SFW-filtered). HTML link generation routes NSFW models to `civitai.red`. The API host itself stays on `civitai.com` (metadata, media, and auth all work there).

**Tech Stack:** Python 3.12, pytest, unittest.mock, PyYAML, Jinja2 (HTML templates).

## Global Constraints

- CivitAI `nsfwLevel` bit flags: `1`=PG, `2`=PG-13, `4`=Mature/R, `8`=X, `16`=XX, `32`=XXX. A version's `nsfwLevel` is the OR of levels present.
- A model is NSFW when version `nsfwLevel >= level_threshold` (default `4`) OR a truthy `nsfw` flag is present.
- Config defaults must be backward-compatible: existing user configs missing the new keys must keep working.
- `api.base_url` stays `https://civitai.com/api/v1`. No per-request API host switching.
- SFW models keep inline by-hash previews (no feed fetch) and stay on the `civitai.com` domain. The header link changes from the bare `/models/{id}` to the version-specific `/models/{id}?modelVersionId={vid}` on both domains — this deep-link is intentional and applies uniformly; only the *domain* is NSFW-conditional.
- Do NOT touch the committed API key in `config/default.yaml` (explicit user decision).
- The `/images` `nsfw` parameter is the CivitAI enum string (`None`/`Soft`/`Mature`/`X`), NOT a boolean.
- Follow existing code style: type hints, module-level `logger = logging.getLogger(__name__)`, docstrings on public functions.

---

### Task 1: NSFW/domain helper module + config defaults

**Files:**
- Create: `civitscraper/api/domains.py`
- Modify: `config/default.yaml` (add keys under `api:`)
- Test: `tests/test_api/test_domains.py` (new)

> **Note:** `civitscraper/config/loader.py` needs NO change. Its shallow `api`-key merge (loader.py:194-197) already copies the new top-level `api.domains` / `api.nsfw` blocks into user configs that omit them, and `get_domain_settings` fills every default itself as a second safety net.

**Interfaces:**
- Consumes: nothing (pure functions + dict config).
- Produces:
  - `DEFAULT_DOMAINS: dict` = `{"sfw": "civitai.com", "nsfw": "civitai.red"}`
  - `DEFAULT_LEVEL_THRESHOLD: int` = `4`
  - `DEFAULT_BROWSING_LEVEL: str` = `"X"`
  - `get_domain_settings(config: dict) -> tuple[dict, int, str]` returns `(domains, level_threshold, browsing_level)`, filling defaults for any missing key.
  - `is_nsfw(metadata: dict, level_threshold: int = 4) -> bool`
  - `model_page_domain(nsfw: bool, domains: dict) -> str`
  - `build_model_url(model_id, version_id, nsfw: bool, domains: dict) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api/test_domains.py`:

```python
"""Tests for NSFW detection and civitai.com/civitai.red domain routing."""

import pytest

from civitscraper.api.domains import (
    DEFAULT_DOMAINS,
    build_model_url,
    get_domain_settings,
    is_nsfw,
    model_page_domain,
)


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({"nsfwLevel": 1}, False),   # PG
        ({"nsfwLevel": 2}, False),   # PG-13
        ({"nsfwLevel": 3}, False),   # PG | PG-13, still below Mature
        ({"nsfwLevel": 4}, True),    # Mature
        ({"nsfwLevel": 60}, True),   # Mature|X|XX|XXX
        ({"nsfw": True}, True),      # explicit top-level flag, no level
        ({"nsfw": False}, False),
        ({"model": {"nsfw": True}}, True),   # real by-hash shape: nsfw nested under model
        ({"model": {"nsfw": False}}, False),
        ({"nsfwLevel": 1, "model": {"nsfw": True}}, True),  # nested flag overrides low level
        ({}, False),                 # missing => SFW
    ],
)
def test_is_nsfw(metadata, expected):
    assert is_nsfw(metadata) is expected


def test_is_nsfw_custom_threshold():
    assert is_nsfw({"nsfwLevel": 2}, level_threshold=2) is True
    assert is_nsfw({"nsfwLevel": 4}, level_threshold=8) is False


def test_model_page_domain():
    assert model_page_domain(True, DEFAULT_DOMAINS) == "civitai.red"
    assert model_page_domain(False, DEFAULT_DOMAINS) == "civitai.com"


def test_build_model_url_with_model_id():
    url = build_model_url(123, 456, True, DEFAULT_DOMAINS)
    assert url == "https://civitai.red/models/123?modelVersionId=456"


def test_build_model_url_sfw():
    url = build_model_url(123, 456, False, DEFAULT_DOMAINS)
    assert url == "https://civitai.com/models/123?modelVersionId=456"


def test_build_model_url_without_model_id():
    # Fallback branch mirrors context.py: no /{model_id} segment.
    url = build_model_url(None, 456, True, DEFAULT_DOMAINS)
    assert url == "https://civitai.red/models?modelVersionId=456"


def test_get_domain_settings_defaults():
    domains, threshold, level = get_domain_settings({})
    assert domains == DEFAULT_DOMAINS
    assert threshold == 4
    assert level == "X"


def test_get_domain_settings_partial_override():
    config = {"api": {"domains": {"nsfw": "custom.red"}, "nsfw": {"level_threshold": 8}}}
    domains, threshold, level = get_domain_settings(config)
    assert domains == {"sfw": "civitai.com", "nsfw": "custom.red"}
    assert threshold == 8
    assert level == "X"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api/test_domains.py -v`
Expected: FAIL (ModuleNotFoundError: no module named `civitscraper.api.domains`).

- [ ] **Step 3: Implement `civitscraper/api/domains.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api/test_domains.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Add config keys**

In `config/default.yaml`, inside the `api:` block, after the `user_agent` line (line 13) and before the `batch:` block (line 16), insert:

```yaml
  # Domain routing: NSFW models live on civitai.red, SFW on civitai.com (split 2026-04-15)
  domains:
    sfw: "civitai.com"     # public/SFW model pages
    nsfw: "civitai.red"    # NSFW model pages
  nsfw:
    level_threshold: 4     # nsfwLevel >= this => treat model as NSFW (4 = Mature+)
    browsing_level: "X"    # /images nsfw value used when fetching NSFW previews
```

- [ ] **Step 6: Commit**

```bash
git add civitscraper/api/domains.py tests/test_api/test_domains.py config/default.yaml
git commit -m "feat: add NSFW detection and civitai.red domain helper"
```

---

### Task 2: `nsfw` parameter on the images endpoint

**Files:**
- Modify: `civitscraper/api/endpoints/images.py` (`ImagesEndpoint.get`)
- Modify: `civitscraper/api/client.py` (`CivitAIClient.get_images`, `get_images_typed`)
- Test: `tests/test_api/test_images_nsfw.py` (new)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `ImagesEndpoint.get(..., nsfw: Optional[str] = None, ...)` — when `nsfw` is not None, adds `params["nsfw"] = nsfw`.
  - `CivitAIClient.get_images(..., nsfw: Optional[str] = None, ...)` — threads `nsfw` to the endpoint.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_images_nsfw.py`:

```python
"""Tests that the images endpoint forwards the nsfw browsing-level parameter."""

from unittest.mock import MagicMock

from civitscraper.api.endpoints.images import ImagesEndpoint


def make_endpoint():
    base = MagicMock()
    base._make_request.return_value = {"items": []}
    return ImagesEndpoint(base), base


def test_get_forwards_nsfw_param():
    endpoint, base = make_endpoint()
    endpoint.get(model_version_id=11745, nsfw="X")
    _, kwargs = base._make_request.call_args
    assert kwargs["params"]["nsfw"] == "X"
    assert kwargs["params"]["modelVersionId"] == 11745


def test_get_omits_nsfw_when_none():
    endpoint, base = make_endpoint()
    endpoint.get(model_version_id=11745)
    _, kwargs = base._make_request.call_args
    assert "nsfw" not in kwargs["params"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_images_nsfw.py -v`
Expected: FAIL (`get()` got an unexpected keyword argument `nsfw`).

- [ ] **Step 3: Implement**

In `civitscraper/api/endpoints/images.py`, change the `get` signature and params. Replace the current signature/params block:

```python
    def get(
        self,
        model_id: Optional[int] = None,
        model_version_id: Optional[int] = None,
        limit: int = 100,
        page: int = 1,
        nsfw: Optional[str] = None,
        force_refresh: bool = False,
        response_type: Optional[type] = None,
    ) -> Union[Dict[str, Any], ImageSearchResult]:
```

Add to the docstring Args: `nsfw: Browsing-level enum (None/Soft/Mature/X) to include NSFW images`.

After the existing `if model_version_id:` block and before `return self._make_request(`, add:

```python
        if nsfw is not None:
            params["nsfw"] = nsfw
```

In `civitscraper/api/client.py`, update `get_images` — add `nsfw: Optional[str] = None` to the keyword-only signature (after `page: int = 1,`) and pass `nsfw=nsfw,` into the `self._images.get(...)` call. `get_images_typed` forwards `**kwargs`, so it needs no change.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api/test_images_nsfw.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add civitscraper/api/endpoints/images.py civitscraper/api/client.py tests/test_api/test_images_nsfw.py
git commit -m "feat: add nsfw browsing-level param to images endpoint"
```

---

### Task 3: NSFW media feed fallback in metadata fetch

**Files:**
- Modify: `civitscraper/scanner/metadata_manager.py` (`MetadataManager.__init__`, `fetch_metadata`)
- Test: `tests/test_scanner/test_nsfw_media.py` (new)

**Interfaces:**
- Consumes: `is_nsfw`, `get_domain_settings` from Task 1; `CivitAIClient.get_images(nsfw=...)` from Task 2.
- Produces: after a by-hash fetch, when the model is NSFW, `metadata["images"]` is replaced with the `/images` feed results (mapped to the inline image dict shape). SFW models are untouched. On empty/failed feed, inline images are kept.

**Behavior detail:** the feed image dicts must match the shape consumed by `image_manager` and `context.py`: keys `id`, `url`, `nsfw`, `width`, `height`, `hash`, `meta`. Feed items expose `nsfwLevel` (int) not `nsfw` (bool); map `nsfw = level >= level_threshold`. The feed is fetched with `typed=False` (raw dicts) to avoid `Image.from_dict` requiring a `nsfw` key the feed does not provide.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scanner/test_nsfw_media.py`:

```python
"""Tests for the NSFW image-feed fallback in MetadataManager.fetch_metadata."""

from unittest.mock import MagicMock

from civitscraper.scanner.metadata_manager import MetadataManager


def make_manager():
    api = MagicMock()
    config = {"api": {"nsfw": {"level_threshold": 4, "browsing_level": "X"}}, "output": {}}
    return MetadataManager(config, api), api


SFW_INLINE = [{"id": 1, "url": "https://image.civitai.com/a.jpeg", "nsfwLevel": 1}]
NSFW_VERSION = {"id": 11745, "modelId": 6424, "nsfwLevel": 60, "images": SFW_INLINE}
SFW_VERSION = {"id": 200, "modelId": 7, "nsfwLevel": 1, "images": SFW_INLINE}

FEED = {
    "items": [
        {
            "id": 99,
            "url": "https://image.civitai.com/x.jpeg",
            "nsfwLevel": 8,
            "width": 512,
            "height": 768,
            "hash": "abc",
            "meta": {"prompt": "p"},
        }
    ]
}


def test_nsfw_model_replaces_images_with_feed():
    mgr, api = make_manager()
    api.get_model_version_by_hash.return_value = dict(NSFW_VERSION)
    api.get_images.return_value = FEED

    metadata = mgr.fetch_metadata("HASH")

    api.get_images.assert_called_once()
    _, kwargs = api.get_images.call_args
    assert kwargs["model_version_id"] == 11745
    assert kwargs["nsfw"] == "X"
    assert len(metadata["images"]) == 1
    img = metadata["images"][0]
    assert img["url"] == "https://image.civitai.com/x.jpeg"
    assert img["nsfw"] is True          # level 8 >= threshold 4
    assert img["meta"] == {"prompt": "p"}


def test_sfw_model_keeps_inline_images():
    mgr, api = make_manager()
    api.get_model_version_by_hash.return_value = dict(SFW_VERSION)

    metadata = mgr.fetch_metadata("HASH")

    api.get_images.assert_not_called()
    assert metadata["images"] == SFW_INLINE


def test_feed_failure_falls_back_to_inline():
    mgr, api = make_manager()
    api.get_model_version_by_hash.return_value = dict(NSFW_VERSION)
    api.get_images.side_effect = RuntimeError("boom")

    metadata = mgr.fetch_metadata("HASH")

    assert metadata["images"] == SFW_INLINE  # unchanged on failure


def test_empty_feed_falls_back_to_inline():
    mgr, api = make_manager()
    api.get_model_version_by_hash.return_value = dict(NSFW_VERSION)
    api.get_images.return_value = {"items": []}

    metadata = mgr.fetch_metadata("HASH")

    assert metadata["images"] == SFW_INLINE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scanner/test_nsfw_media.py -v`
Expected: FAIL (`get_images` called with unexpected kwargs / not called; images not replaced).

- [ ] **Step 3: Implement**

In `civitscraper/scanner/metadata_manager.py`:

Add imports near the top (after the existing `from ..api.client import CivitAIClient`):

```python
from ..api.domains import get_domain_settings, is_nsfw
```

In `__init__`, after `self.output_config = config.get("output", {})`, add:

```python
        _, self.nsfw_threshold, self.nsfw_browsing_level = get_domain_settings(config)
        # Preview count cap for the NSFW image feed (mirrors image download limit).
        self.nsfw_feed_limit = (
            self.output_config.get("images", {}).get("max_count") or 20
        )
```

In `fetch_metadata`, replace the validation block that currently reads:

```python
            # Validate required fields
            if not metadata.get("images"):
                logger.warning(f"No images found in metadata for hash {file_hash}")
                return None
```

with:

```python
            # For NSFW models the inline by-hash images are browsing-level
            # filtered (SFW only). Pull the full media set from the images feed
            # with an explicit nsfw browsing level instead.
            if is_nsfw(metadata, self.nsfw_threshold):
                feed_images = self._fetch_nsfw_images(
                    metadata.get("id"), force_refresh
                )
                if feed_images:
                    metadata["images"] = feed_images

            # Validate required fields
            if not metadata.get("images"):
                logger.warning(f"No images found in metadata for hash {file_hash}")
                return None
```

Add a new method to the class (e.g. after `fetch_metadata`):

```python
    def _fetch_nsfw_images(
        self, version_id: Optional[int], force_refresh: bool
    ) -> List[Dict[str, Any]]:
        """Fetch the NSFW image feed for a version and map to inline shape.

        Returns an empty list on any failure so the caller keeps inline images.
        """
        if not version_id:
            return []
        try:
            response = self.api_client.get_images(
                model_version_id=version_id,
                nsfw=self.nsfw_browsing_level,
                limit=self.nsfw_feed_limit,
                force_refresh=force_refresh,
            )
            items = response.get("items", []) if isinstance(response, dict) else []
            mapped: List[Dict[str, Any]] = []
            for item in items:
                level = item.get("nsfwLevel", 0)
                mapped.append(
                    {
                        "id": item.get("id"),
                        "url": item.get("url"),
                        "nsfw": bool(
                            isinstance(level, (int, float))
                            and level >= self.nsfw_threshold
                        ),
                        "width": item.get("width"),
                        "height": item.get("height"),
                        "hash": item.get("hash"),
                        "meta": item.get("meta"),
                    }
                )
            return mapped
        except Exception as e:
            logger.warning(f"Failed to fetch NSFW image feed for version {version_id}: {e}")
            return []
```

(`Optional`, `List`, `Dict`, `Any` are already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scanner/test_nsfw_media.py -v`
Expected: PASS (all four cases).

- [ ] **Step 5: Commit**

```bash
git add civitscraper/scanner/metadata_manager.py tests/test_scanner/test_nsfw_media.py
git commit -m "feat: fetch NSFW previews from images feed with browsing level"
```

---

### Task 4: HTML model-page link routing to civitai.red

**Files:**
- Modify: `civitscraper/html/context.py` (`ContextBuilder.__init__`, `build_model_context`, `_build_sibling_versions_context`, `merge_gallery_models` staticmethod; `VersionIndexCache.get_model_versions`)
- Modify: `civitscraper/html/generator.py:214` (pass `domains` into the `merge_gallery_models` call)
- Modify: `civitscraper/html/templates/components/header.html` (the `<a href>`, line 6)
- Test: `tests/test_html/test_domain_links.py` (new)

> **Constraint:** `merge_gallery_models` is a `@staticmethod` (context.py:397) and is called class-style in 8 existing tests (`ContextBuilder.merge_gallery_models(cards)` in `tests/test_html/test_context_merge.py`). It MUST stay static. Thread `domains` in as an optional parameter defaulting to `DEFAULT_DOMAINS` so those calls keep working; do NOT reference `self` inside it.

**Interfaces:**
- Consumes: `is_nsfw`, `get_domain_settings`, `build_model_url` from Task 1.
- Produces: `build_model_context` returns context including `model_url`; all remote sibling/version links route via `build_model_url` using the model's NSFW status; `header.html` renders `{{ model_url }}`.

**Threading note:** `VersionIndexCache` is a module-level singleton without config. `get_model_versions` gains `nsfw` and `domains` parameters, passed by the (config-aware) `ContextBuilder`. All versions of one model share that model's NSFW status.

- [ ] **Step 1: Write the failing test**

Create `tests/test_html/test_domain_links.py`:

```python
"""Tests that model-page links route to civitai.red for NSFW models."""

from civitscraper.html.context import ContextBuilder


_CB_CONFIG = {
    "api": {},
    "output": {
        "metadata": {
            "path": "{model_dir}",
            "filename": "{model_name}.json",
            "html": {"filename": "{model_name}.html"},
        }
    },
}


def make_builder():
    return ContextBuilder(_CB_CONFIG)


def test_model_url_nsfw_routes_to_red(tmp_path):
    builder = make_builder()
    model_file = tmp_path / "m.safetensors"
    model_file.write_text("x")
    metadata = {
        "id": 456,
        "modelId": 123,
        "nsfwLevel": 60,
        "images": [],
        "model": {"name": "N", "type": "LORA"},
    }
    ctx = builder.build_model_context(str(model_file), metadata)
    assert ctx["model_url"] == "https://civitai.red/models/123?modelVersionId=456"


def test_model_url_sfw_routes_to_com(tmp_path):
    builder = make_builder()
    model_file = tmp_path / "m.safetensors"
    model_file.write_text("x")
    metadata = {
        "id": 456,
        "modelId": 123,
        "nsfwLevel": 1,
        "images": [],
        "model": {"name": "N", "type": "LORA"},
    }
    ctx = builder.build_model_context(str(model_file), metadata)
    assert ctx["model_url"] == "https://civitai.com/models/123?modelVersionId=456"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_html/test_domain_links.py -v`
Expected: FAIL (`KeyError: 'model_url'`).

- [ ] **Step 3: Implement context changes**

In `civitscraper/html/context.py`:

Add import after the existing local imports (`from .sanitizer import DataSanitizer`):

```python
from ..api.domains import build_model_url, get_domain_settings, is_nsfw
```

In `ContextBuilder.__init__`, after `self.config = config`, add:

```python
        self.domains, self.nsfw_threshold, _ = get_domain_settings(config)
```

In `build_model_context`, after `parent_model_id = ...` (the line computing `parent_model_id`), add:

```python
        model_nsfw = is_nsfw(metadata, self.nsfw_threshold)
```

Pass `model_nsfw` into the sibling-versions call by adding it as an argument:

```python
        sibling_versions = self._build_sibling_versions_context(
            file_path,
            metadata.get("siblingVersions", []),
            parent_model_id,
            metadata.get("id"),
            model_nsfw,
        )
```

Add `model_url` to the returned `context` dict (alongside `parent_model`):

```python
            "model_url": build_model_url(
                parent_model_id, metadata.get("id"), model_nsfw, self.domains
            ),
```

Update `_build_sibling_versions_context` signature to accept `model_nsfw: bool` (add as the last parameter). Replace the remote-link `else` branch (currently building `https://civitai.com/models...`) with:

```python
            else:
                version_data["is_local"] = False
                version_data["link"] = build_model_url(
                    parent_model_id, version_id, model_nsfw, self.domains
                )
```

Where that method calls `_version_index_cache.get_model_versions(current_dir, parent_model_id, current_version_id)`, change it to pass routing info:

```python
            merged = _version_index_cache.get_model_versions(
                current_dir, parent_model_id, current_version_id, model_nsfw, self.domains
            )
```

In `VersionIndexCache.get_model_versions`, add parameters `nsfw: bool = False, domains: Optional[Dict[str, str]] = None` and, at the top of the body, `domains = domains or DEFAULT_DOMAINS`. Replace the hardcoded remote-link line:

```python
                entry["link"] = (
                    f"https://civitai.com/models/{model_id}?modelVersionId={vid}"
                )
```

with:

```python
                entry["link"] = build_model_url(model_id, vid, nsfw, domains)
```

Combine the domains import created above into one line so `DEFAULT_DOMAINS` is also available:

```python
from ..api.domains import DEFAULT_DOMAINS, build_model_url, get_domain_settings, is_nsfw
```

In `_process_gallery_model` (the instance method that builds each card dict, return block at context.py:376-395 — `self` is in scope), add `"nsfw": is_nsfw(metadata, self.nsfw_threshold),` next to `"model_id": metadata.get("modelId"),` (line ~390).

`merge_gallery_models` is a `@staticmethod` (line 397) — it has NO `self`. Change its signature from:

```python
    @staticmethod
    def merge_gallery_models(models_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
```

to:

```python
    @staticmethod
    def merge_gallery_models(
        models_data: List[Dict[str, Any]],
        domains: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
```

At the top of its body add:

```python
        domains = domains or DEFAULT_DOMAINS
```

In its merged-card sibling-link block (line ~478), replace:

```python
                            "link": (
                                f"https://civitai.com/models/{model_id}" f"?modelVersionId={sib_id}"
                            ),
```

with:

```python
                            "link": build_model_url(
                                model_id, sib_id, representative.get("nsfw", False), domains
                            ),
```

(`Optional`, `Dict` are already imported at the top of context.py.)

Then in `civitscraper/html/generator.py`, line 214, update the call to pass the builder's domains:

```python
        models_data = self.context_builder.merge_gallery_models(
            models_data, self.context_builder.domains
        )
```

- [ ] **Step 4: Update the template**

In `civitscraper/html/templates/components/header.html`, the `<a href>` line (line 6, inside the existing `{% if metadata and metadata.modelId %}` guard), replace:

```html
            <a href="https://civitai.com/models/{{ metadata.modelId }}" class="external-link" target="_blank">
```

with:

```html
            <a href="{{ model_url }}" class="external-link" target="_blank">
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_html/test_domain_links.py tests/test_html/ -v`
Expected: PASS (new tests pass; existing HTML tests still pass).

- [ ] **Step 6: Commit**

```bash
git add civitscraper/html/context.py civitscraper/html/generator.py civitscraper/html/templates/components/header.html tests/test_html/test_domain_links.py
git commit -m "feat: route NSFW model-page links to civitai.red"
```

---

### Task 5: Full-suite regression + docs note

**Files:**
- Modify: `readme.md` or `CONFIGURATION.md` (document the new `api.domains` / `api.nsfw` config keys)
- Test: entire suite

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: PASS (no regressions). If existing tests assert `https://civitai.com/models...` for NSFW-tagged fixtures, update those fixtures/assertions to the new domain behavior and re-run.

- [ ] **Step 2: Document config keys**

Add a short section to `CONFIGURATION.md` (or `readme.md` if that file is absent) describing:
- `api.domains.sfw` / `api.domains.nsfw` — public domains for SFW/NSFW model pages.
- `api.nsfw.level_threshold` — `nsfwLevel` at/above which a model is treated as NSFW (default 4 = Mature).
- `api.nsfw.browsing_level` — the `/images` `nsfw` value (`None`/`Soft`/`Mature`/`X`) used to fetch NSFW previews.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: document civitai.red / NSFW config keys"
```

---

## Self-Review

**Spec coverage:**
- New `api/domains.py` helper → Task 1. ✓
- NSFW media feed fallback (endpoint param, client, metadata_manager) → Tasks 2, 3. ✓
- HTML link routing (header.html + context.py sibling/gallery links) → Task 4. ✓
- Config keys + backward-compatible defaults → Task 1 (default.yaml + `get_domain_settings` defaults). ✓
- Security (leaked key) → explicitly out of scope per user decision; not a task. ✓
- Tests for is_nsfw / domain / URL builder / endpoint param / feed fallback / context links → Tasks 1–4. ✓

**Type consistency:** `get_domain_settings` returns `(domains, threshold, browsing_level)` and is unpacked consistently in metadata_manager (`_, threshold, level`) and context (`domains, threshold, _`). `build_model_url(model_id, version_id, nsfw, domains)` signature used identically in Tasks 1 and 4. `get_images(..., nsfw=...)` defined in Task 2 and called with `nsfw=` in Task 3. Feed image mapping keys (`id/url/nsfw/width/height/hash/meta`) match the inline shape in `metadata_manager.fetch_metadata`. Consistent.

**Placeholders:** none — all steps contain concrete code and commands.

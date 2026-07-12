# civitai.red Support — Design

**Date:** 2026-07-12
**Status:** Approved (pending user spec review)

## Background

On 2026-04-15 CivitAI split its site into two domains:

- `civitai.com` — SFW-only public site (the former "green" domain).
- `civitai.red` — hosts NSFW models, including their metadata, images, and videos.

CivitScraper currently only knows about `civitai.com`. This work makes it correctly
handle red-hosted (NSFW) models.

## Live investigation findings (2026-07-12)

Tested directly against both domains with a real API token:

1. **Metadata is identical on both domains.** `GET /api/v1/model-versions/by-hash/{hash}`
   returns the same NSFW model (e.g. model 827184, `nsfwLevel: 60`) with the same inline
   images on `civitai.com` and `civitai.red`. The scraper's core hash lookup already works
   against either host.
2. **The API token works on both domains now.** An old client bug (comfy-cli #435, Apr 2026)
   where tokens were rejected on `civitai.red/api` has since been fixed. `/api/v1/me` returns
   HTTP 200 on both.
3. **Media CDN is unchanged.** All image/video URLs point to `image.civitai.com` on both
   domains.
4. **NSFW media is gated by a request parameter, not by domain.** The `/api/v1/images`
   endpoint returns only SFW images (`nsfwLevel` 1–2) unless `nsfw=X` (an enum, not a boolean)
   is passed. With `nsfw=X` it returns the full set (`Soft`/`Mature`/`X`). This behaves
   identically on `civitai.com` and `civitai.red`.
5. **The by-hash inline image list is browsing-level filtered** to the account's server-side
   level and cannot be un-filtered by a query parameter. It is the source the scraper currently
   downloads from, which is why NSFW previews are missing.

### Conclusions that shape the design

- **"Missing NSFW media" is not a domain problem — it is a missing `nsfw` parameter.**
  The fix is to fetch previews for NSFW models from the `/images` endpoint with a configured
  `nsfw` level. This works on either host.
- **`civitai.red` matters only for public model-page links.** NSFW models are hidden on
  `civitai.com`'s public site, so a `civitai.com/models/{id}` link dead-ends. Those links must
  point to `civitai.red` for NSFW models.
- **The API host does not need to change.** Metadata, media, and auth all work on
  `civitai.com`. No per-request host switching.

## Goals

- Fetch NSFW images/videos for NSFW models (primary pain point).
- Generate model-page links that resolve for NSFW models (route to `civitai.red`).
- Choose the domain automatically per model from its metadata (no per-run config).
- Leave SFW model behavior unchanged.

## Non-goals

- No per-request API host switching (API stays on `civitai.com`).
- No global domain switch.
- No change to SFW preview fetching (keeps inline by-hash images).
- No change to the CDN image-resize logic (`context.py` ~line 952).
- No handling of the committed API key in `config/default.yaml` (flagged separately;
  user will rotate it). Left untouched by explicit decision.

## NSFW classification

CivitAI `nsfwLevel` is a bit-flag scale: `1`=PG, `2`=PG-13, `4`=Mature/R, `8`=X,
`16`=XX, `32`=XXX. A version's `nsfwLevel` is the OR of the levels present in it
(e.g. `60` = `4|8|16|32`).

**A model is treated as NSFW when its version `nsfwLevel >= 4` (Mature+), or a truthy
`nsfw` flag is present.** Threshold configurable. PG / PG-13 models stay SFW.

## Components

### 1. New module: `civitscraper/api/domains.py`

Single source of truth for NSFW detection and domain/URL selection. Pure functions,
independently testable, no I/O.

```
is_nsfw(metadata: dict, threshold: int = 4) -> bool
    True if metadata["nsfwLevel"] >= threshold, or metadata.get("nsfw") is truthy.

model_page_domain(nsfw: bool, domains: dict) -> str
    Returns domains["nsfw"] (civitai.red) when nsfw else domains["sfw"] (civitai.com).

build_model_url(model_id, version_id, nsfw, domains) -> str
    Builds "https://{domain}/models/{model_id}?modelVersionId={version_id}",
    omitting the "/{model_id}" segment when model_id is falsy (matches the current
    fallback branch in context.py).
```

`domains` and `threshold` come from config (see §4); callers pass resolved values so the
module stays dependency-free.

### 2. NSFW media feed fallback

**`api/endpoints/images.py::get()`** — add a `nsfw: Optional[str] = None` parameter and,
when set, include `params["nsfw"] = nsfw` in the request. (The endpoint currently sends no
`nsfw` param at all.) Value is the CivitAI enum string (`None`/`Soft`/`Mature`/`X`).

**`api/client.py::get_images()` / `get_images_typed()`** — add matching `nsfw` parameter,
thread it to the endpoint.

**`scanner/metadata_manager.py::fetch_metadata()`** — after building `metadata`:

```
if is_nsfw(metadata, threshold):
    fetch /images?modelVersionId=metadata["id"]&nsfw=browsing_level  (limit = max_count or a cap)
    if results:
        metadata["images"] = [mapped image dicts]
```

The mapped dict matches the existing inline shape consumed by `image_manager` and
`context.py`: keys `id`, `url`, `nsfw`, `width`, `height`, `hash`, `meta`. Feed images
carry a `type` field (`image`/`video`); videos flow through `image_manager`'s existing
Content-Type detection, so no extra handling is needed.

If the feed call fails or returns nothing, fall back to the existing inline images (never
worse than today). SFW models skip this branch entirely — behavior unchanged.

The `browsing_level` and `threshold` are read from config once and passed in.

### 3. HTML link routing

**`templates/components/header.html:6`** — replace the hardcoded
`https://civitai.com/models/{{ metadata.modelId }}` with `{{ model_url }}`, a new context
variable.

**`html/context.py::build_model_context()`** — compute `model_url` via
`build_model_url(parent_model_id, metadata.get("id"), is_nsfw(metadata), domains)` and add
it to the returned context.

**`html/context.py` sibling-version link builders** (lines ~102, ~478, ~646/653) — replace
the hardcoded `https://civitai.com/models` strings with `build_model_url(...)` using the
model's NSFW status. All versions of one model share that model's NSFW status.

**`html/context.py::build_gallery_context()`** — add a per-card `nsfw` boolean (from
`is_nsfw(metadata)`) so the merged-card sibling links (line ~478) route to the correct
domain. The version-index cache path (line ~102) resolves NSFW status from the indexed
version metadata.

`VersionIndexCache` and the context builders receive `domains`/`threshold` from the config
already threaded into `ContextBuilder`.

### 4. Configuration

New keys under `api:` in `config/default.yaml`, all with backward-compatible defaults so
existing user configs keep working:

```yaml
api:
  # ... existing keys ...
  domains:
    sfw: "civitai.com"     # public/SFW model pages
    nsfw: "civitai.red"    # NSFW model pages
  nsfw:
    level_threshold: 4     # nsfwLevel >= this ⇒ treat model as NSFW
    browsing_level: "X"    # /images nsfw value used for NSFW models
```

`base_url` remains `https://civitai.com/api/v1`. Loader defaults (`config/loader.py`) fill
these in when absent, mirroring the existing default-merge behavior for the `api` section.

## Data flow (NSFW model)

```
hash → by-hash (civitai.com API) → metadata (nsfwLevel >= 4)
     → is_nsfw = True
     → /images?modelVersionId=…&nsfw=X → full media list → metadata["images"]
     → image_manager downloads media from image.civitai.com
     → context: model_url + version links → civitai.red/models/…
     → HTML page with resolving links + NSFW previews
```

SFW model: skips the feed call, uses inline images, links stay on `civitai.com`.

## Error handling

- Feed fetch failure / empty → keep inline images, log at debug/info. Never regress SFW-level
  content that was already obtainable.
- Missing `nsfwLevel` in metadata → treated as SFW (threshold not met), safe default.
- Missing `model_id` in URL builder → omit the segment (existing fallback behavior).
- Unknown/absent config keys → loader supplies defaults.

## Testing

- `is_nsfw`: threshold boundaries (3/4/8), `nsfw` flag true/false, missing field.
- `model_page_domain` / `build_model_url`: SFW→.com, NSFW→.red, missing model_id fallback.
- `images.py` / `client.get_images`: `nsfw` param present in request when set, absent when None.
- `metadata_manager.fetch_metadata`: NSFW model triggers feed and replaces images; SFW model
  does not; feed failure falls back to inline images.
- `context.py`: `model_url` and sibling links use `.red` for NSFW, `.com` for SFW; gallery card
  carries `nsfw`.

## Files touched

- `civitscraper/api/domains.py` (new)
- `civitscraper/api/endpoints/images.py`
- `civitscraper/api/client.py`
- `civitscraper/scanner/metadata_manager.py`
- `civitscraper/html/context.py`
- `civitscraper/html/templates/components/header.html`
- `config/default.yaml`
- `civitscraper/config/loader.py` (defaults for new keys, if needed)
- tests under `tests/`

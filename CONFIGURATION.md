# Advanced Configuration

This document details the advanced configuration options for CivitScraper, typically found in your `config/default.yaml` file (or a custom configuration file). For basic setup, refer to the main [README.md](readme.md).

At start-up CivitScraper warns about keys it does not know, since those are ignored. A typo then shows up as, for example, `Unknown config key jobs.fetch-all.skip_exisiting (did you mean skip_existing?); it is ignored`. Unknown keys are only reported, never rejected.

## Table of Contents
- [API Configuration](#api-configuration)
- [Output Location Configuration](#output-location-configuration)
- [HTML Generation Configuration](#html-generation-configuration)
- [Advanced Organization Settings](#advanced-organization-settings)
- [Keeping Models Up to Date](#keeping-models-up-to-date)
- [Sorting Models into the Right Folders](#sorting-models-into-the-right-folders)
- [Downloading Updates](#downloading-updates)
- [Scanner Settings (Caching)](#scanner-settings-caching)
- [Logging Configuration](#logging-configuration)
- [Batch Processing Details](#batch-processing-details)

## API Configuration

The `api` section configures the connection to the CivitAI API, including performance tuning and safety mechanisms.

```yaml
api:
  key: "your_api_key"                # Your CivitAI API key (Optional, but recommended)
  base_url: "https://civitai.com/api/v1"  # API endpoint
  timeout: 30             # [seconds] API request timeout
  max_retries: 3         # Number of times to retry failed requests (excluding rate limits)
  user_agent: "CivitScraper/0.2.0"  # User agent string for requests

  # Domain routing for the civitai.com / civitai.red split (2026-04-15)
  domains:
    sfw: "civitai.com"     # public domain for SFW model pages
    nsfw: "civitai.red"    # domain for NSFW model pages
  nsfw:
    level_threshold: 4     # nsfwLevel >= this => model treated as NSFW (4 = Mature+)
    browsing_level: "X"    # /images nsfw value used to fetch NSFW previews

  # Batch processing settings (See Batch Processing Details below)
  batch:
    enabled: true         # Enable batch processing for metadata fetching
    max_concurrent: 4     # Maximum parallel requests using thread-safe semaphore
    rate_limit: 100       # Target requests/minute (uses token bucket with per-endpoint tracking)
    retry_delay: 1000     # Base delay (ms) for exponential backoff when rate limited
    cache_size: 100       # LRU cache size for API responses - evicts least recently used entries when full

    # Circuit breaker prevents API abuse during outages by tracking failures per endpoint
    circuit_breaker:
      failure_threshold: 5    # Number of consecutive failures before blocking requests to an endpoint
      reset_timeout: 60       # Seconds to wait before attempting recovery after blocking
```

-   **`timeout`**: How long to wait for a response from the CivitAI API before giving up.
-   **`max_retries`**: How many times to retry a request if it fails due to network issues or server errors (5xx). Does not apply to rate limit errors (429).
-   **`user_agent`**: Identifies CivitScraper to the CivitAI API.
-   **`key`**: Your CivitAI API key. While optional for fetching public data, providing a key is recommended as it may grant higher rate limits from the CivitAI API.
-   **`domains`**: Public domains for model-page links. Since 2026-04-15 CivitAI serves SFW models on `civitai.com` and NSFW models on `civitai.red`. Links in generated HTML are routed per-model based on NSFW classification. `base_url` (the API host) stays on `civitai.com` — metadata, media, and auth all resolve there for both SFW and NSFW models.
-   **`nsfw.level_threshold`**: The CivitAI `nsfwLevel` at or above which a model is treated as NSFW (bit flags: `1`=PG, `2`=PG-13, `4`=Mature/R, `8`=X, `16`=XX, `32`=XXX). Default `4`. NSFW models route to the `nsfw` domain and pull previews from the images feed.
-   **`nsfw.browsing_level`**: The `nsfw` enum (`None`/`Soft`/`Mature`/`X`) sent to the images endpoint when fetching NSFW previews. The inline by-hash image list is browsing-level filtered (SFW only), so NSFW models fetch their full media set from the feed with this level. Default `X` (all).
-   **`batch`**: Settings related to processing multiple files concurrently. See [Batch Processing Details](#batch-processing-details).
-   **`circuit_breaker`**: Settings for automatically stopping requests to specific API endpoints if they consistently fail. See [Batch Processing Details](#batch-processing-details).

## Output Location Configuration

By default, metadata JSON, preview images, and per-model HTML files are all written next to the model file itself, using the `{model_dir}` placeholder in `output.metadata.path` / `output.images.path` / `output.metadata.html.path` (each defaults to `"{model_dir}"`).

If you'd rather keep model folders containing only the model files, set `output.base_dir` to redirect metadata, images, and per-model HTML to one central directory, organized by model type:

```yaml
output:
  base_dir: "~/civitai-data"   # Optional. Default: unset (write next to model file).
  metadata:
    filename: "{model_name}.json"
  images:
    filenames:
      preview: "{model_name}.preview{ext}"
```

- `base_dir` supports `~` and `${VAR}`/`$VAR` expansion.
- When set, output is written to `base_dir/{model_type}/<filename>` — the `path` settings under `output.metadata`, `output.images`, and `output.metadata.html` are ignored for the directory portion (filename templates still apply).
- When unset, behavior is unchanged from today.
- `output.metadata.html.gallery_path` is unaffected — it's a separate, fixed path for the shared gallery index page, not per-model output. It can point at the same directory as `base_dir` with no conflict.
- `organization.output_dir` is also unaffected — that setting relocates the model file itself, a separate feature from metadata/image/HTML output.
- **Caveat**: two different model files that share the same name and model type, but live in different source folders, will collide under `base_dir/{model_type}/` — the second will overwrite the first's output.
- `{model_type}` comes from the most specific `input_paths` entry that contains the model file. A model organized to an absolute `organization.output_dir` outside every input path resolves to `Unknown`.
- Model cards (HTML) are expected in the same directory as their metadata sidecar (true for the default layout and for `base_dir`). Custom `output.metadata.path` and `output.metadata.html.path` values pointing at *different* directories work for writing, but the gallery's "existing model cards" scan and local version links only find cards that sit next to their sidecar.
- All readers (skip_existing, cached-metadata jobs, the gallery, `sync-lora-triggers`, organization) use these same locations. For `sync-lora-triggers`, put `output.base_dir` / `output.metadata` either at the top level of the config or in the sync job itself; the legacy `<model>.json` next to the model is used as a fallback.

## HTML Generation Configuration

The HTML generation feature creates individual model cards and gallery pages for your models. The configuration allows fine-grained control over when HTML files are generated.

```yaml
# Example within a job's output configuration
output:
  metadata:
    html:
      enabled: true                 # Enable HTML generation
      filename: "{model_name}.html" # HTML filename pattern
      skip_existing_html: true      # Skip existing HTML files (independent of metadata skip_existing)
      generate_gallery: true        # Generate a gallery page with all models
      gallery_path: "path/to/model_gallery.html"  # Gallery output path
      gallery_title: "Model Gallery"              # Gallery page title
      portable_paths: true          # Gallery links relative to the gallery (default true)
```

### Key Settings

-   **`enabled`**: Controls whether HTML generation is active for this job.
-   **`filename`**: Pattern for individual model HTML files. Uses the same placeholders as organization templates.
-   **`skip_existing_html`**: **New Feature** - Controls HTML regeneration independently of metadata fetching.
-   **`generate_gallery`**: Creates a gallery page that lists all processed models.
-   **`gallery_path`**: Location for the gallery HTML file.
-   **`gallery_title`**: Title displayed on the gallery page.
-   **`portable_paths`** (default `true`): links in the gallery are relative to the gallery file. The gallery then keeps working when the whole tree moves together: the gallery and the model folders copied to another disk, or a NAS mounted at a different path or drive letter. A path on another Windows drive than the gallery stays absolute. Set it to `false` if you move only the gallery folder and leave the models where they are.

### Gallery Features

-   **Views**: *Cards*, *Wall* (dense image wall) and *Table* (sortable columns). A slider sets the card size.
-   **One card per model and base model.** A CivitAI model with versions for several base models (a "Chair" LoRA for MOSS and for Krea 2) gets one card per base model you have. Each card lists the others under *Also for* in the quick look, together with versions on CivitAI for base models you use (learned from your folders, see [Downloading Updates](#downloading-updates)).
-   **Group** (the folder button next to the views): drill down by *type* › *base model* › *your folders* below the base folder (`LORA › Krea 2 › style › anime`). Each group is a tile with up to four previews, the number of models, their size on disk, the newest addition and its health counts. Click a tile to open it; the path above the tiles (and the browser's Back button, or `Backspace`) goes back up. A level with only one group is skipped. Searching shows matching models from every group, each with its group path; clearing the search returns to where you were. Filters narrow the groups and their counts. The choice is remembered, and works with every view.
-   **Search** matches model name, trigger words, tags, creator, type, base model, folder, version and the description. Words are combined (`anime style` finds models matching both); `"blue hair"` matches the exact phrase. Press `/` to search.
-   **Filters** by health, model type, base model, folder and creator. Within one filter any selected value matches; across filters all must match.
-   **Quick look**: press `Space` on a card (or click its eye button) for a side panel with every trigger word, the file path, versions, duplicates, tags and the description. `←`/`→` step through the results. Click a tag to search for it.
-   **Copy buttons** copy one trigger word, all of them (comma-separated, ready to paste into a prompt), the model file path or its folder.
-   **Collection health** (chips above the results, and the *Health* filter):
    -   *Update available*: CivitAI has a version newer than every local version on the same base model. A new SDXL release does not flag a model you only keep for SD 1.5.
    -   *No preview*: no preview image was found.
    -   *Duplicate*: the same CivitAI version is stored at two or more locations. Organized copies and symlinks (copy/symlink mode) are not counted.
    -   *Also for other bases*: not a problem, a filter: CivitAI has versions of the model for base models you use that you do not have yet.
    -   *Removed from CivitAI*: CivitAI no longer lists the version (or the whole model). The card and page show the last data fetched; nothing local is deleted. See [Keeping Models Up to Date](#keeping-models-up-to-date).
    -   *Not on CivitAI*: scanned files that have no sidecar because CivitAI answered "not found" for their hash. Other files without a sidecar (never looked up, or the lookup failed) are listed as *No metadata yet*. Both are in the collapsible panel above the results.
-   **Blur NSFW** blurs previews of models above `api.nsfw.level_threshold` until you hover them. The setting is remembered.
-   **Light and dark theme**: follows the system setting; the moon/sun button switches it.
-   Filters, search, sort and view are part of the page address, so a filtered view can be bookmarked. Going back from a model page returns to the same place in the gallery.
-   Version lists (and so *Update available*) are as fresh as each model's last refresh (at most `scanner.refresh_after_days`, 14 by default).

### Model Pages

-   The first screen holds what you need to use a model: previews, trigger words (click to copy), the file with "Copy path" / "Copy folder", all versions (local ones link to their page) and tags.
-   Click a preview for the viewer: prompt, negative prompt and settings. **Copy for Forge** (or `C`) copies them in the A1111/Forge format; paste into the prompt box and use "Read generation parameters". `←`/`→` browse, `I` hides the details, `Esc` closes.
-   Pages are self-contained (styles and scripts inlined) and keep working when the collection is moved together with them.

### HTML Regeneration Without API Calls

The new `skip_existing_html` setting allows you to regenerate HTML files without refetching metadata from the CivitAI API. This is useful when you want to:

- Update HTML templates or styling
- Regenerate HTML with different settings
- Fix HTML generation issues

**Example Configuration for HTML Regeneration:**

```yaml
regenerate-html:
  type: scan-paths
  use_cached_metadata: true    # Only models with an existing sidecar; no API calls
  paths: ["lora"]
  output:
    metadata:
      html:
        enabled: true
        skip_existing_html: false  # Force HTML regeneration
        generate_gallery: true
    images:
      save: false              # Don't re-download images
```

This configuration will:
1. Use existing cached metadata files (no API calls, no hashing)
2. Regenerate all HTML files even if they exist
3. Skip image downloading
4. Create a new gallery page

### `verify_hashes`

Models are identified on CivitAI by their file hash, so `scan-paths` jobs always hash files for API lookups. `verify_hashes: false` is ignored there (a warning is logged); use `use_cached_metadata: true` to work without hashing or API calls.

## Advanced Organization Settings

While basic organization is covered in the main README, here are the details for custom templates and available placeholders.

```yaml
# Example within a job definition
organization:
  enabled: true             # Enable model organization
  dry_run: false            # Simulate file operations without making changes
  template: "by_type_and_basemodel"  # Predefined template (if custom_template is empty)
  custom_template: "{type}/{creator|Unknown Creator}/{base_model|Unknown Base}" # Custom path structure
  output_dir: "{model_dir}/organized"  # Base directory for organized files
  operation_mode: "symlink"    # [copy/move/symlink] How to organize files
```

Re-running organization is safe:

- **copy / symlink**: files inside the organization output are not scanned again (the originals are), and the original keeps its own metadata sidecar so `skip_existing` works for it.
- **move**: moved files stay in the scan (they are the only copy) but are never re-organized, so repeated runs cannot nest them deeper.
- Metadata, HTML and previews move along with the model to the locations their path settings dictate. With `output.base_dir` they usually stay where they are.

### Custom Templates

You can define your own directory structure using the `custom_template` setting. If `custom_template` is provided, it overrides the `template` setting.

The template string uses placeholders that will be replaced with metadata values.

### Available Placeholders

-   `{model_name}`: Model name
-   `{model_id}`: Model ID on CivitAI
-   `{version_id}`: Model Version ID on CivitAI
-   `{type}`: Model type (e.g., `LORA`, `Checkpoint`)
-   `{creator}`: Creator username
-   `{base_model}`: Base model (e.g., `SD 1.5`, `SDXL 1.0`)
-   `{nsfw}`: NSFW status (`true`/`false` or `sfw`/`nsfw` depending on context, usually `true`/`false` in paths)
-   `{year}`: Creation year (from model version)
-   `{month}`: Creation month (numeric, e.g., `01`, `12`)
-   `{day}`: Creation day (numeric)
-   `{rating}`: Raw rating (e.g., `4.5`)
-   `{rating_count}`: Number of ratings
-   `{download_count}`: Number of downloads
-   `{thumbs_up_count}`: Number of thumbs-up reactions
-   `{weighted_rating}`: Calculated weighted rating (0.0-5.0, rounded to nearest 0.5, e.g., `3.5`)
-   `{weighted_thumbsup}`: Calculated weighted thumbs-up rating (1.0-5.0, e.g., `4.0`)

**Default Values:** You can specify a default value if a metadata field is missing using a pipe (`|`):
`{creator|Unknown Creator}` will use "Unknown Creator" if the creator field is not present in the metadata.

**Path Sanitization:** The organizer automatically sanitizes generated paths to remove characters that are invalid in directory or file names.

## Krita AI Diffusion Integration

The `sync-lora-triggers` job copies each LoRA's trigger words (`trainedWords`) into Krita's `loras.json`:

```yaml
sync-triggers:
  type: sync-lora-triggers
  loras_file: "path/to/loras.json"
  overwrite_triggers: true   # false keeps triggers already set in Krita
  paths: ["lora"]
```

- `--dry-run` (or `dry_run: true`) reports what would change without touching the file.
- Before changing `loras.json`, the previous version is saved as `loras.json.bak`; the file is written atomically and left untouched when nothing changed.

## Keeping Models Up to Date

`scan-paths` jobs look up new model files by hash. Models that already have a sidecar are refreshed once their data is older than `scanner.refresh_after_days` (default 14), also with `skip_existing: true`:

```yaml
scanner:
  refresh_after_days: 14    # 0 turns automatic refreshes off
  refresh_max_per_run: 100  # oldest first; the rest follow on later runs
```

-   A refresh asks CivitAI for the version by its id (no re-hashing) and updates the sidecar: stats, description, trigger words, files, images and, through the parent model, the version list and tags. Keys CivitAI does not send are kept, e.g. the "activation text", "preferred weight" and "notes" Forge's Lora editor writes into the same file.
-   **Previews follow CivitAI without losing anything.** Files are matched to images by CivitAI's image id, not by position:
    -   When the creator reorders the images, the files are renamed so every prompt stays with its picture.
    -   New images are downloaded into free slots (up to `output.images.max_count`).
    -   Images the creator removed stay on disk as *archived* previews: shown after the current ones as "No longer on CivitAI", with their prompt and settings, and not counted against `max_count`.
    -   For NSFW models the previews come from CivitAI's community image feed, whose selection changes all the time. Those previews keep their numbers; a refresh only fills empty slots.
    -   No preview file is ever deleted or overwritten. To download a preview again, delete its file.
-   **Models removed from CivitAI** (the version or the whole model answers "not found") keep their sidecar, previews and page exactly as they were. They are flagged *Removed from CivitAI* in the gallery and on their page, with the date it was noticed.
-   Network errors, server errors and rate limits change nothing; the model is tried again on the next run. Other refusals (e.g. early access) just move the next check back.
-   `skip_existing: false` refreshes every file now (by hash), with the same rules. Offline jobs (`use_cached_metadata: true`) never refresh.
-   Sidecars Forge wrote on its own (without CivitAI data) are looked up like new files; their keys are kept.
-   The job summary counts new, refreshed and removed models.

## Sorting Models into the Right Folders

With many models it is easy to drop a LoRA into the wrong base model's folder. The `sort-models` job finds such files and moves them, with their sidecar, page and previews:

```yaml
input_paths:
  lora:         { path: "models/Lora", type: LORA, patterns: ["*.safetensors"] }
  unet:         { path: "models/unet", type: Checkpoint, patterns: ["*.safetensors", "*.gguf"] }
  vae:          { path: "models/VAE", type: VAE, patterns: ["*.safetensors"] }                # optional
  text_encoder: { path: "models/text_encoder", type: TextEncoder, patterns: ["*.safetensors"] }  # optional

jobs:
  sort:
    type: sort-models
    paths: ["lora", "unet", "vae", "text_encoder"]

sorting:                       # all optional
  regenerate_job: regenerate-html   # rebuilds pages and gallery after moving (default: regenerate-html)
  decisions_file: sort-decisions.json   # your answers; relative to the config file
  gallery_flag: true           # flag misplaced models in the gallery
  base_folders:                # only needed where the folders cannot be learned
    "Illustrious": SDXL         # put this base model into an existing folder
    "Flux.1 D": { lora: Flux, checkpoint: flux1-dev }
  krita:
    enabled: true              # update Krita AI Diffusion's LoRA paths after moves
    # loras_file: defaults to the sync-lora-triggers job's loras_file
    # styles_dir: defaults to <krita data>/styles
```

```bash
civitscraper -j sort --dry-run   # report only
civitscraper -j sort             # walk through each suggestion in the terminal
civitscraper -j sort --yes       # move only the confident ones, without asking
civitscraper -j sort --undo      # move the last run's models back
```

**What a model really is.** Two independent sources are compared:

-   The CivitAI sidecar: matched by the file's hash, so it describes this exact file. Its base model is chosen by the uploader and is sometimes wrong.
-   The file itself: the header of a `.safetensors` or `.gguf` file lists every tensor. Its layout tells a LoRA from a LoKr, a full checkpoint, a VAE or a text encoder, and is compared with the files you already have CivitAI data for. Training metadata (`ss_base_model_version`) counts as a hint once your labelled files show what it stands for. Only the header is read; pickle files (`.pt`, `.ckpt`) are never opened.

Base models built on the same architecture (Pony, Illustrious and SDXL, for example) cannot be told apart by the file. There, CivitAI's label decides and the file never contradicts it.

**Where it belongs.** Below each input path, the first folder level is the base model folder (`Lora/SDXL`); deeper folders are your categories (`style`, `character`) and are kept when a file moves (`SDXL/style/x` goes to `Flux/style/x`; an existing `Style` folder is reused). Which folder stands for which base model is learned: a folder holds a base model when at least 60 % of its (at least 3) labelled files are of that base. `sorting.base_folders` overrides or extends this. An input path without base folders is not sorted. A file directly in the input path or in a folder that stands for no base model (an inbox such as `pre-sort`) is *not sorted yet* and gets a suggestion too.

**The walk-through** shows, for each suggestion, what CivitAI says, what the file looks like and where it would go:

```
[1/2] Lora/SDXL/concept/ember_glow.safetensors  (LoRA · in another base model's folder)
  CivitAI    Flux.1 D · LORA
  Structure  Flux.1 D · 100% like your 2 labelled Flux.1 D LoRA file(s)
  Move to    Lora/Flux/concept/ember_glow.safetensors  (+6 file(s))
  [y] move  [n] keep here  [s] skip  [o] other folder  [a] all SDXL/concept → Flux/concept  [q] quit
```

-   `n` remembers to keep the file where it is; it is not suggested again (also not in the gallery). `s` skips it for this run only.
-   `o` asks for another folder and can remember "this base model goes in that folder" for all its files.
-   `a` moves every following file from the same folder to the same target without asking.
-   When CivitAI and the file disagree, you choose `[c]` follow CivitAI or `[f]` follow the file; the choice is remembered.
-   Files whose architecture is unknown are only asked about when they are not in a base model folder, and the default answer is to leave them.
-   Answers are kept in `sorting.decisions_file`, keyed by the file's content, so they survive renames and moves.

`--yes` moves only suggestions that are safe without a look: a single target inside the same input path, an existing folder, and CivitAI data (or an unambiguous file). New folders, moves between input paths (a checkpoint lying in `Lora/`), conflicts and unknown files always wait for the walk-through. VAE and text encoder files are only reported, never moved: they are often shared by several base models.

**Safety.**

-   Nothing is ever overwritten or deleted. Before a model moves, every target is checked; if any file is in the way, the model stays where it is. Each move is atomic and refuses an existing target; a move to another drive is refused rather than copied.
-   If a move fails halfway, the files already moved go back.
-   Files that changed in the last five minutes, or that have a `.part` download next to them, are left alone. So are models with an unfinished preview update.
-   Every run is journaled in `<cache_dir>/sort-journal/`. An interrupted run is finished at the start of the next one. `--undo` moves the last run's models back, including previews downloaded since, and removes folders the run created if they are empty.
-   Files next to a model that the sorter does not know (`<model>.notes.txt`) are left in place and listed.
-   Hashes are carried over, so moved files are not hashed again.
-   Afterwards the pages and the gallery are rebuilt by the `regenerate_job`, so all links point to the new places.

**Krita.** Krita AI Diffusion refers to LoRAs by their path inside the LoRA folder (`SDXL/style/x.safetensors`). After moving LoRAs, the sorter replaces exactly those paths in Krita's `loras.json` and in the LoRA lists of its styles; nothing else in those files changes, and a timestamped backup is written first. If Krita is running you are asked first (with `--yes`, the update is skipped). `--undo` changes the paths back.

**In the gallery,** `scan-paths` jobs flag misplaced models (*In the wrong folder*), with the suggested folder in the quick look, and the job summary reports how many there are. Set `sorting.gallery_flag: false` to turn this off.

## Downloading Updates

The `download-updates` job offers the newer versions the gallery flags as *Update available* and downloads the ones you pick, next to the version you have:

```yaml
jobs:
  # Put it last: it runs the fetch and trigger-sync jobs itself after downloading.
  updates:
    type: download-updates
    paths: ["lora", "unet", "checkpoints"]

updates:                         # all optional
  auto_max_size_mb: 2048         # --yes downloads free updates up to this size
  min_free_gb: 5                 # keep this much disk space free
  archive_dir: "~/model-archive"  # where archived old versions go (default: <models>/_archive)
  decisions_file: update-decisions.json   # your answers; relative to the config file
  # after_jobs: [fetch-all, sync-triggers]   # default: the first scan-paths job that
  #                                          # calls CivitAI, plus every sync-lora-triggers job
  krita:
    enabled: true                # point Krita's references at the new LoRA (paths: sorting.krita)
```

```bash
civitscraper -j updates --dry-run   # report only
civitscraper -j updates             # choose in the terminal, then download
civitscraper -j updates --yes       # only small free updates, old versions kept
civitscraper -j updates --undo      # revert the last run
```

**The API key is required.** CivitAI only lets logged-in users download, SFW models included. The `api.key` (or `CIVITAI_API_KEY`) is all it takes, for NSFW models (civitai.red) too; no browser login is needed. The key is only sent to the CivitAI API, never to the storage server the download is redirected to. Without a key the job only reports.

**What counts as an update** is the gallery's rule: a version newer than every version you have *on the same base model*. A new SDXL version is never offered for your SD 1.5 copy. When there are several newer versions, the newest is offered and `[v]` lists the others.

**Which file.** A version can offer several files (fp16 and fp32, full and pruned, GGUF quantizations). The one most like yours is chosen: same format, same quantization, same precision. It must have an extension its folder is scanned for. `[f]` picks another one. The file keeps CivitAI's name and goes into the folder of the version you have, so your folder layout stays as it is. If that name is taken, `<name>_v<version id>` is used; nothing is ever overwritten.

**The walk-through** asks all questions first and then downloads one file at a time, so you can walk away while it runs:

```
[2/7] Lora/Flux/style/ember_glow_v1.safetensors   (LORA · Flux.1 D)
  You have  v1.0 · 2026-03-02
  New       v2.0 · 2026-10-14 · 144.0 MB · SafeTensor fp16   (1 more newer version(s): [v])
  Notes     Retrained on 400 images, better hands
  Triggers  ember glow, warm light  (was: ember glow)
  Links     https://civitai.com/models/...  https://civitai.red/models/...
  Save as   Lora/Flux/style/ember_glow_v2.safetensors
  [y] download  [n] not this version  [i] ignore this model  [v] other version  [f] other file  [s] skip  [q] quit
  Old version after download: [k] keep  [a] archive  [t] trash  (default k)
```

-   `n` remembers "not this version", including the older ones in between; a later version is offered again. `i` never offers updates for the model again. Both also hide the gallery's update flag. `s` skips for this run only.
-   **Old version.** `keep` (the default) leaves it in place. `archive` moves it, with its sidecar, page and previews, to `<archive_dir>/<folder>/<same subfolders>` (e.g. `_archive/Lora/Flux/style/`). `updates.archive_dir` takes `~`, `$VARS` and paths relative to the config file, and a job can set its own; the default is `_archive` next to your model folders. It must be outside every scanned folder and on the same drive (archiving moves, it never copies); otherwise the job says so up front and does not offer `archive`. `trash` moves it to the desktop Trash (Linux), where you can restore it from your file manager. The old version is only touched once the new file is downloaded, verified and has its CivitAI data.
-   **Early access and paid versions** cannot be downloaded with an API key. They are listed with their links and the end date, and offered as soon as they are free.

**Downloads.**

-   Each download is checked against CivitAI's SHA256 before it is put in place; a file that does not match is discarded.
-   An interrupted download (network, Ctrl-C) is kept as `<file>.part` and resumed on the next run. If you choose not to resume, you are asked whether to delete the partial file.
-   Before each file, the free disk space is checked.

**Afterwards** the job runs the fetch job for the new files (sidecar, previews, page, gallery; the file is not hashed again) and the trigger sync. Then it archives or trashes the old versions you chose, and rebuilds the pages. Without a terminal and without `--yes` it only reports, so it can run every time as part of `--all-jobs`.

**Versions for other base models.** CivitAI authors often put variants for several base models into one model (a "Chair" LoRA for MOSS Image, Krea 2 and Pony). After the updates, the walk-through offers these too, but only for base models you use: a base counts when one of your LoRA or checkpoint folders holds it (learned like the sort job does, from where most of your files are), plus `updates.base_models`:

```yaml
updates:
  base_models:              # optional
    add: ["Qwen 2.1"]       # offer these too, even without a folder yet
    skip: ["ZImageTurbo"]   # never offer versions for these
  # base_models: ["Qwen 2.1"]   # a plain list means "add"
```

-   The newest version on each such base is offered, even if it is older than yours: it is a different model, not an update. `[v]` lists the others on that base.
-   It is saved in that base's folder, with your category folders kept (`Lora/MOSS/style/chair` → `Lora/krea2/style/`). A folder that does not exist yet, or another model folder, is marked on the card, and `[o]` picks another folder.
-   The version you have is always kept. `--yes` never downloads versions for other bases.
-   `n` hides that version (and older ones on that base) until a newer one appears; `[b]` never offers this model for that base again; `[x]` skips all the remaining ones for this run.
-   Some models mix types, e.g. a full checkpoint uploaded as a version of a LoRA. A file far bigger (or smaller) than its type suggests is marked on the card and proposed for the checkpoint (or LoRA) folder. After the download the file's header is checked like the sort job does; if it is another type than its folder, you are asked whether to move it there.

**Re-uploads.** A "newer" version whose file has the same SHA256 as a file you already have (the same file uploaded twice) is not offered, and it no longer flags an update. The next version is offered instead.

**Krita.** When an old LoRA is archived or trashed, Krita's LoRA entry moves to the new file and keeps its strength and other settings; the trigger words become the new version's. Styles that used the old LoRA use the new one, with the same strength. A timestamped backup is written first, and `--undo` reverts it. A kept LoRA is left alone; Krita adds the new one itself, and the trigger sync fills in its trigger words once Krita lists it.

**Undo.** Every run is journaled in `<cache_dir>/update-journal/`. `--undo` moves the downloaded files (and the pages made for them) to the Trash, brings archived and trashed old versions back, and restores Krita's references. With `--all-jobs --undo`, the sort and the update job each undo their last run.

## Scanner Settings (Caching)

The `scanner` section controls caching behavior to reduce redundant API calls.

```yaml
scanner:
  cache_dir: ".civitscraper_cache"  # Directory to store cache files (API responses)
  cache_validity: 86400            # [seconds] How long cache entries are considered valid (default: 24 hours)
  force_refresh: false             # Global flag to ignore cache and always fetch fresh data
  not_found_validity: 604800       # [seconds] Don't re-query hashes CivitAI answered 404 for (7 days)
  hash_workers: 4                  # Parallel hash + lookup workers (set 1 for spinning HDDs)
```

-   **`cache_dir`**: Specifies the directory where API responses are cached locally.
-   **`cache_validity`**: Determines the maximum age (in seconds) of a cached response before it's considered stale and needs refreshing.
-   **`force_refresh`**: If set to `true` globally (or via the `--force-refresh` command-line flag), the cache will be ignored entirely for the run.

-   **File hashes**: a model's SHA-256 is cached in `cache_dir/file_hashes/` and reused while the file's size and modification time are unchanged, so unchanged models are never re-read. `--rehash` ignores the cached hashes.
-   **`not_found_validity`**: models that are not on CivitAI (404 by hash) are remembered and not looked up again for this long. Network errors, server errors and rate limits are never remembered. A model uploaded to CivitAI only minutes ago can briefly 404 by hash; run with `--force-refresh` to look it up immediately.
-   **`hash_workers`**: how many files are hashed and looked up in parallel. 4 suits SSD/NVMe; use 1 for spinning hard disks (parallel reads make them seek) and 2 for network shares.

The API client uses an LRU (Least Recently Used) cache in memory (`api.batch.cache_size`) for frequently accessed items during a single run, while the `scanner.cache_dir` provides persistent caching between runs.

## Logging Configuration

Control the level and destination of log messages.

```yaml
logging:
  level: DEBUG                     # Overall minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

  # Console output settings
  console:
    enabled: true                  # Enable logging to the console
    level: INFO                    # Minimum level for console messages
    simple: false                  # Use detailed format (includes timestamp, level, module) if false, simpler format if true

  # File logging settings
  file:
    enabled: true                  # Enable logging to a file
    level: DEBUG                   # Minimum level for file messages
    directory: logs                # Directory to store log files
    filename: civitscraper.log     # Base name for log files
    max_size: 10                   # [MB] Maximum size before rotating the log file
    backup_count: 5                # Number of backup log files to keep (e.g., civitscraper.log.1, .2, etc.)
```

-   Set `level` under `logging`, `console`, and `file` to control verbosity. `DEBUG` is the most verbose.
-   `simple: true` in `console` provides less detailed output, suitable for general use.
-   File logging (`file.enabled: true`) creates rotating logs in the specified `directory`.

## Batch Processing Details

CivitScraper uses batch processing primarily for fetching metadata from the CivitAI API efficiently.

```yaml
# Relevant settings under api.batch:
api:
  batch:
    enabled: true         # Enable/disable batch processing
    max_concurrent: 4     # Max parallel API requests at any time
    rate_limit: 100       # Target requests/minute
    retry_delay: 1000     # Base delay (ms) for retrying after rate limit (429 error)
    cache_size: 100       # In-memory LRU cache size for API responses during a run
    download_rate_limit: 300  # Image downloads/minute (separate from API calls)
    download_workers: 4   # Models whose previews download in parallel
    circuit_breaker:
      failure_threshold: 5 # Consecutive failures to trigger breaker
      reset_timeout: 60    # Seconds before retrying a broken circuit
```

-   **`enabled`**: `false` makes hashing and metadata lookups sequential.
-   **`max_concurrent`**: Maximum number of simultaneous metadata API requests. Files are hashed by `scanner.hash_workers` threads; this caps how many of them talk to the API at once.
-   **`rate_limit`**: Token bucket for CivitAI API calls (requests per minute).
-   **`download_rate_limit`** (default 300/min) and **`download_workers`** (default 4): preview downloads from the image CDN have their own bucket and run for several models at once. Your API key is only ever sent to the API host, never to image or other hosts.
-   **HTTP 429**: CivitAI's `Retry-After` header (seconds or HTTP date, capped at 5 minutes) is honored; without it the client backs off exponentially from `retry_delay`. Rate limiting does not count toward the circuit breaker.
-   **`cache_size`**: An in-memory LRU cache stores recent API responses during a run to avoid refetching the same data multiple times within that run.
-   **`circuit_breaker`**: Monitors consecutive failures for each API endpoint (e.g., `/models/{id}`, `/images`). If an endpoint fails `failure_threshold` times in a row, the breaker "opens," and further requests to that specific endpoint are blocked for `reset_timeout` seconds to allow the API to recover. This prevents hammering a potentially failing service.

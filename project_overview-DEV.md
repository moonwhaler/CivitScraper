# CivitScraper - Developer & Architecture Overview

## Project Summary

CivitScraper is a Python CLI application that automates the management of AI model files from CivitAI. It scans local directories for model files (LoRAs, Checkpoints, etc.), fetches metadata via the CivitAI API, downloads preview images, generates HTML preview pages, and optionally organizes files into structured directories.

**Version:** 0.2.0
**License:** AGPL-3.0
**Python:** >= 3.8

---

## Project Structure

```
civitscraper/
├── civitscraper/                 # Main package
│   ├── __init__.py               # Package exports
│   ├── cli.py                    # CLI entry point
│   ├── api/                      # CivitAI API client layer
│   ├── config/                   # Configuration loading
│   ├── html/                     # HTML generation
│   ├── jobs/                     # Job execution system
│   ├── organization/             # File organization
│   ├── scanner/                  # File discovery & processing
│   └── utils/                    # Utilities (caching, hashing, logging)
├── config/
│   └── default.yaml              # Default configuration
├── tests/                        # Test suite
├── pyproject.toml                # Package configuration
├── setup.py                      # Setup script
└── requirements*.txt             # Dependencies
```

---

## Core Architecture

### High-Level Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   CLI       │────▶│ JobExecutor │────▶│   Scanner   │
│  (cli.py)   │     │ (executor)  │     │ (processor) │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                    │
                           ▼                    ▼
                    ┌─────────────┐     ┌─────────────┐
                    │  Organizer  │     │  API Client │
                    │             │     │             │
                    └─────────────┘     └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │    HTML     │
                                        │  Generator  │
                                        └─────────────┘
```

### Processing Phases (scan-paths job)

1. **Discovery**: Scan directories for model files matching patterns
2. **Hashing**: Compute BLAKE3 hashes for model identification
3. **API Fetch**: Query CivitAI API using hashes to get metadata
4. **Enrichment**: Fetch parent model data for version info (deduplicated)
5. **Organization**: Move/copy/symlink files to structured directories (optional)
6. **Image Download**: Download preview images from CivitAI
7. **Metadata Save**: Write JSON metadata files alongside models
8. **HTML Generation**: Create individual model pages and gallery

---

## Module Documentation

### Entry Point: `civitscraper/cli.py`

| Component | Purpose |
|-----------|---------|
| `parse_args()` | Parse CLI arguments (--job, --config, --dry-run, etc.) |
| `main()` | Application entry point; loads config, initializes client, runs jobs |

**CLI Options:**
- `-c, --config`: Custom config file path
- `-j, --job`: Run specific job
- `--all-jobs`: Run all defined jobs
- `--dry-run`: Simulate file operations
- `--force-refresh`: Ignore cache
- `--debug`: Enable debug logging

---

### Configuration: `civitscraper/config/`

```
config/
├── __init__.py
└── loader.py              # YAML loading and validation
```

| Component | Purpose |
|-----------|---------|
| `load_yaml_config()` | Load YAML file to dict |
| `load_config()` | Priority-based config loading (CLI > env > user > default) |
| `merge_configs()` | Deep merge two config dicts |
| `validate_config()` | Validate required fields (input_paths, api) |
| `load_and_validate_config()` | Combined load + validate + env override |

**Config Loading Priority:**
1. CLI `--config` path
2. `CIVITSCRAPER_CONFIG` environment variable
3. User paths: `./civitscraper.yaml`, `~/.config/civitscraper/config.yaml`
4. Default: `./config/default.yaml`

---

### API Layer: `civitscraper/api/`

```
api/
├── __init__.py            # Package exports
├── base_client.py         # Base HTTP client with rate limiting
├── client.py              # High-level CivitAI client
├── circuit_breaker.py     # Failure tracking per endpoint
├── rate_limiter.py        # Token bucket rate limiting
├── request.py             # HTTP request handling
├── response.py            # Response parsing
├── models.py              # Data models (Model, ModelVersion, Image, etc.)
├── exceptions.py          # Custom exceptions
└── endpoints/             # API endpoint implementations
    ├── __init__.py
    ├── base.py            # Base endpoint class
    ├── models.py          # /models endpoint
    ├── versions.py        # /model-versions endpoint
    └── images.py          # /images endpoint
```

#### `CivitAIClient` (client.py)

Main client facade providing typed and untyped API methods:

| Method | Purpose |
|--------|---------|
| `get_model(id)` | Fetch model by ID |
| `get_model_by_hash(hash)` | Fetch model by file hash |
| `get_model_version(id)` | Fetch version by ID |
| `get_model_version_by_hash(hash)` | Fetch version by hash (primary lookup) |
| `search_models(**filters)` | Search with filters |
| `get_images(model_id, version_id)` | Fetch images for model/version |
| `download_image(url, path)` | Download image file |
| `get_parent_model_with_versions()` | Fetch parent model with sibling versions |

#### `BaseClient` (base_client.py)

Low-level HTTP client with resilience patterns:

```python
class BaseClient:
    rate_limiter: RateLimiter      # Token bucket for request throttling
    circuit_breaker: CircuitBreaker # Per-endpoint failure tracking
    cache_manager: CacheManager     # LRU + disk caching
    request_handler: RequestHandler # HTTP with retries
```

#### `RateLimiter` (rate_limiter.py)

Token bucket algorithm for API rate limiting:

- Configurable requests per minute/second
- Thread-safe with blocking acquire
- Auto-refill based on elapsed time

```python
# Example: 1000 requests/minute
limiter = RateLimiter(1000, per_second=False)
limiter.acquire()  # Blocks if bucket empty
```

#### `CircuitBreaker` (circuit_breaker.py)

Prevents API abuse during outages:

- Tracks failures per endpoint
- Opens circuit after `failure_threshold` failures
- Auto-resets after `reset_timeout` seconds

```python
breaker = CircuitBreaker(failure_threshold=20, reset_timeout=30)
if breaker.is_open("/models"):
    raise CircuitBreakerOpenError()
breaker.record_failure("/models")  # Increment failure count
breaker.record_success("/models")  # Reset failure count
```

---

### Job System: `civitscraper/jobs/`

```
jobs/
├── __init__.py
└── executor.py            # Job orchestration
```

#### `JobExecutor` (executor.py)

Orchestrates job execution based on configuration:

| Job Type | Description |
|----------|-------------|
| `scan-paths` | Main job: scan, fetch, process, organize, generate |
| `sync-lora-triggers` | Sync trigger words to Krita's loras.json |

**Execution Flow (scan-paths):**

```
execute_job()
    ├── find_model_files()           # Discovery
    ├── filter_files()               # Skip existing/cached
    ├── PHASE 1: Fetch metadata      # API calls per file
    ├── PHASE 1.5: Enrich versions   # Deduplicated parent fetch
    ├── PHASE 2: Organize files      # FileOrganizer
    ├── PHASE 3: Download images     # ImageManager
    ├── PHASE 4: Save & process      # Metadata + HTML
    └── PHASE 5: Generate gallery    # HTMLGenerator.generate_gallery()
```

---

### Scanner Module: `civitscraper/scanner/`

```
scanner/
├── __init__.py
├── discovery.py           # File finding and filtering
├── processor.py           # Main ModelProcessor coordinator
├── file_processor.py      # Single file processing + hashing
├── batch_processor.py     # Batch processing with progress
├── metadata_manager.py    # API fetch + JSON save
├── image_manager.py       # Image downloading
├── html_manager.py        # HTML generation wrapper
└── version_enricher.py    # Parent model enrichment
```

#### `ModelProcessor` (processor.py)

Central coordinator for file processing:

```python
class ModelProcessor:
    metadata_manager: MetadataManager  # API + save
    image_manager: ImageManager        # Download images
    html_manager: HTMLManager          # Generate HTML
    file_processor: ModelFileProcessor # Hash files
    batch_processor: BatchProcessor    # Batch with progress
```

| Method | Purpose |
|--------|---------|
| `fetch_metadata(path)` | Hash file, query API, return metadata |
| `save_and_process_with_metadata()` | Save JSON, download images, generate HTML |
| `process_file(path)` | Full pipeline for single file |
| `process_files(paths)` | Parallel processing with ThreadPoolExecutor |

#### `discovery.py`

File discovery and path utilities:

| Function | Purpose |
|----------|---------|
| `find_files(dir, patterns)` | Glob search with recursion option |
| `find_model_files(config, path_ids)` | Find files for configured paths |
| `filter_files(files, skip_existing)` | Filter out files with existing metadata |
| `has_metadata(path)` | Check if .json exists |
| `get_metadata_path(path, config)` | Calculate metadata file path |
| `get_html_path(path, config)` | Calculate HTML file path |
| `get_image_path(path, config, type)` | Calculate image file path |
| `find_html_files(config, path_ids)` | Find existing HTML for gallery |

#### `VersionEnricher` (version_enricher.py)

Optimized parent model fetching with deduplication:

```python
class VersionEnricher:
    # Groups files by modelId, fetches each parent once
    # Caches failed lookups (404s) for 7 days
    # Adds parentModel and siblingVersions to metadata
```

| Method | Purpose |
|--------|---------|
| `enrich_batch(metadata_dict)` | Batch enrich with deduplication |
| `enrich_single(metadata)` | Enrich single metadata dict |
| `clear_failed_cache()` | Clear 404 cache |

---

### HTML Generation: `civitscraper/html/`

```
html/
├── __init__.py
├── generator.py           # Main HTMLGenerator
├── renderer.py            # Jinja2 template rendering
├── context.py             # Template context building
├── paths.py               # Path resolution
├── images.py              # Image path handling
├── sanitizer.py           # JSON/HTML sanitization
└── templates/             # Jinja2 templates + assets
    ├── base.html          # Base layout
    ├── model.html         # Model detail page (self-contained)
    ├── gallery.html       # Gallery overview
    ├── components/        # Reusable components
    ├── css/               # Stylesheets
    └── js/                # JavaScript
```

#### `HTMLGenerator` (generator.py)

| Method | Purpose |
|--------|---------|
| `generate_html(path, metadata)` | Generate single model page |
| `generate_gallery(paths, output, title)` | Generate gallery with all models |

#### Template Structure

```
templates/
├── base.html                 # Gallery uses this
├── model.html                # Self-contained (inlines CSS)
├── gallery.html              # Extends base.html
├── components/
│   ├── header.html           # Page header
│   ├── footer.html           # Page footer
│   ├── model_info.html       # Stats display
│   ├── model_card.html       # Gallery card
│   ├── model_list_item.html  # List view item
│   ├── image_viewer.html     # Fullscreen modal
│   └── related_versions.html # Version switcher
├── css/
│   ├── base.css              # Base styles
│   ├── components.css        # Shared components
│   ├── model.css             # Model page styles
│   └── gallery.css           # Gallery styles
└── js/
    ├── base.js               # Base JavaScript
    └── gallery.js            # Filtering, sorting, infinite scroll
```

**See also:** `model-gallery-details.md` for complete HTML generation documentation.

---

### File Organization: `civitscraper/organization/`

```
organization/
├── __init__.py
├── organizer.py           # FileOrganizer coordinator
├── config.py              # OrganizationConfig dataclass
├── operations.py          # FileOperationHandler (copy/move/symlink)
├── path_formatter.py      # Template-based path formatting
└── models.py              # Data models
```

#### `FileOrganizer` (organizer.py)

| Method | Purpose |
|--------|---------|
| `get_target_path(path, metadata)` | Calculate organized path without action |
| `organize_file(path, metadata)` | Organize single file + related files |
| `organize_files(paths, metadata_dict)` | Batch organize |

#### `PathFormatter` (path_formatter.py)

Template-based path generation with metadata placeholders:

**Built-in Templates:**
- `by_rating`: `{weighted_rating}/{type}`
- `by_type_and_rating`: `{type}/{weighted_rating}`
- `by_type_and_creator`: `{type}/{creator}`
- `by_type_and_basemodel`: `{type}/{base_model}`
- `by_base_model`: `{base_model}/{type}`
- `by_nsfw`: `{nsfw}/{type}`
- `by_date`: `{year}/{month}/{type}`

**Available Placeholders:**
| Placeholder | Description |
|-------------|-------------|
| `{type}` | Model type (LORA, Checkpoint) |
| `{base_model}` | Base model (SDXL 1.0, Pony) |
| `{creator}` | Creator username |
| `{rating}` | Rounded raw rating |
| `{weighted_rating}` | Confidence-adjusted rating |
| `{weighted_thumbsup}` | Thumbs-up ratio rating |
| `{nsfw}` | "nsfw" or "sfw" |
| `{year}`, `{month}` | Creation date components |
| `{model_name}` | Model name |

#### `FileOperationHandler` (operations.py)

Handles file operations with collision policies:

| Operation | Behavior |
|-----------|----------|
| `symlink` | Create symbolic link (recommended, safe) |
| `copy` | Duplicate files |
| `move` | Move files (destructive) |

| Collision Policy | Behavior |
|------------------|----------|
| `skip` | Don't overwrite existing |
| `overwrite` | Replace existing |
| `fail` | Raise error |

---

### Utilities: `civitscraper/utils/`

```
utils/
├── __init__.py
├── cache.py               # LRU + Disk caching
├── hash.py                # File hashing
└── logging.py             # Logging setup + progress
```

#### Caching System (cache.py)

```python
class LRUCache[T]:
    # Thread-safe in-memory LRU cache
    # Evicts least recently used on capacity overflow

class DiskCache[T]:
    # Persistent JSON file cache with TTL
    # Includes in-memory LRU for hot items

class CacheManager[T]:
    # Combines LRU + Disk caching
    # Memory cache fronts disk cache
```

**Cache Hierarchy:**
1. In-memory LRU (fast, limited size)
2. Disk cache (persistent, JSON files)
3. API (on cache miss)

#### File Hashing (hash.py)

| Algorithm | Use Case |
|-----------|----------|
| `blake3` | Primary hash for CivitAI lookup (fast) |
| `sha256` | Fallback if blake3 unavailable |
| `autov1` | SHA256 of first 1MB |
| `autov2` | Full SHA256 |
| `crc32` | Quick checksum |

```python
compute_file_hash(path, algorithm="blake3")  # Returns hex string
compute_file_hashes(path, ["blake3", "sha256"])  # Multiple algorithms
```

---

## Configuration Reference

### Top-Level Structure

```yaml
api:                    # API client settings
input_paths:            # Model directories (required)
default_job:            # Default job name
jobs:                   # Job definitions (required)
scanner:                # Cache settings
logging:                # Log configuration
```

### Job Configuration (scan-paths)

```yaml
jobs:
  job-name:
    type: scan-paths
    paths: ["path-id1", "path-id2"]
    recursive: true                    # Search subdirectories
    skip_existing: true                # Skip files with metadata
    verify_hashes: true                # Verify file hashes
    use_cached_metadata: false         # Load from .json instead of API
    force_refresh: false               # Ignore cache

    output:
      metadata:
        format: json
        path: "{model_dir}"
        filename: "{model_name}.json"
        html:
          enabled: true
          filename: "{model_name}.html"
          skip_existing_html: false
          generate_gallery: true
          gallery_path: "/path/to/gallery.html"
          gallery_title: "My Gallery"
      images:
        save: true
        path: "{model_dir}"
        max_count: 4

    organization:
      enabled: false
      template: "by_type_and_basemodel"
      custom_template: "{type}/{base_model}"
      output_dir: "/path/to/organized"
      operation_mode: symlink           # symlink|copy|move
      on_collision: skip                # skip|overwrite|fail
```

---

## Key Design Patterns

### 1. Phased Processing
Jobs execute in distinct phases with clear dependencies:
- Enables parallel operations within phases
- Allows organized paths to be calculated before image download
- Separates concerns (fetch → organize → generate)

### 2. Batch Deduplication
Parent model fetching groups files by `modelId`:
- One API call per unique parent model
- Results shared across all files of same model
- Failed lookups cached for 7 days

### 3. Multi-Layer Caching
```
Request → Memory LRU → Disk Cache → API
                ↓             ↓
            (100 items)  (JSON files, 24h TTL)
```

### 4. Resilience Patterns
- **Rate Limiting**: Token bucket with blocking acquire
- **Circuit Breaker**: Per-endpoint failure tracking
- **Retries**: Exponential backoff with configurable attempts

### 5. Template-Based Paths
All output paths use configurable templates:
- `{model_dir}`, `{model_name}`, `{model_type}`
- Organization templates for directory structure
- Sanitization of invalid path characters

---

## Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=civitscraper --cov-report=html

# Pre-commit checks
pre-commit run --all-files
```

**Test Structure:**
```
tests/
├── conftest.py           # Fixtures
├── test_cli.py           # CLI tests
├── test_api/
│   └── test_client.py    # API client tests
└── test_config/
    └── test_loader.py    # Config loader tests
```

---

## Dependencies

**Runtime:**
- `requests` - HTTP client
- `pyyaml` - YAML configuration
- `jinja2` - HTML templates
- `blake3` - Fast file hashing

**Development:**
- `pytest`, `pytest-cov` - Testing
- `black`, `isort` - Formatting
- `flake8`, `mypy` - Linting
- `pre-commit` - Git hooks

---

## Related Documentation

- **[CLAUDE.md](CLAUDE.md)** - AI assistant instructions
- **[CONFIGURATION.md](CONFIGURATION.md)** - Full configuration reference
- **[model-gallery-details.md](model-gallery-details.md)** - HTML generation details
- **[readme.md](readme.md)** - User documentation

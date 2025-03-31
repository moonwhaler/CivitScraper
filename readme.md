# CivitScraper - Organize Your AI Models

Tired of messy AI model folders? CivitScraper is your digital curator, transforming raw files into a structured, searchable archive. It automatically organizes your models, fetches metadata and images from CivitAI, and creates browsable HTML previews.

![Example of a generated HTML file](civiscraper_html_example.png)

**Key Benefits:**

*   **Automatic Organization**: Structure your model files logically based on metadata (type, creator, base model, etc.).
*   **Rich Metadata**: Fetch comprehensive details from CivitAI (tags, descriptions, trigger words, ratings).
*   **Visual Previews**: Generate HTML pages for each model with preview images and key info.
*   **Gallery View**: Create a single HTML gallery page to browse your entire collection.
*   **Automation**: Process large collections efficiently with batching and flexible job definitions.

## Table of Contents

-   [Quick Start Guide](#quick-start-guide)
-   [Core Concepts](#core-concepts)
-   [Installation](#installation)
-   [Basic Configuration](#basic-configuration)
-   [Running CivitScraper](#running-civitscraper)
-   [Key Features (In Detail)](#key-features-in-detail)
    -   [Scanning & Identification](#scanning--identification)
    -   [Metadata Retrieval](#metadata-retrieval)
    -   [Image Downloading](#image-downloading)
    -   [HTML Preview Generation](#html-preview-generation)
    -   [File Organization](#file-organization)
    -   [Job System](#job-system)
    -   [Krita AI Diffusion Integration](#krita-ai-diffusion-integration)
    -   [API Handling (Batching, Caching, etc.)](#api-handling-batching-caching-etc)
-   [Advanced Configuration](#advanced-configuration)
-   [Troubleshooting](#troubleshooting)
-   [Development](#development)
-   [License](#license)

## Quick Start Guide

Get up and running in a few steps:

1.  **Install:**
    ```bash
    git clone https://github.com/moonwhaler/civitscraper.git
    cd civitscraper
    python -m venv venv
    # Activate: venv\Scripts\activate (Windows) or source venv/bin/activate (macOS/Linux)
    pip install -e .
    ```

2.  **Configure:**
    *   Copy `config/default.yaml.example` or `config/default.yaml.minimal` to `config/default.yaml`.
    *   Edit `config/default.yaml` and set **at least**:
        *   One input path, e.g., for your LORA models:
          ```yaml
          input_paths:
            lora:
              path: "/path/to/your/lora/models" # <-- Change this path!
              type: LORA
              patterns: ["*.safetensors", "*.pt"]
          ```
        *   Your CivitAI API key (Optional, but recommended for better rate limits): `api.key: "YOUR_API_KEY"`
          ```yaml
          api:
            key: "YOUR_API_KEY_HERE" # Optional: Get from CivitAI account settings
          ```

3.  **Run:**
    ```bash
    civitscraper
    ```
    This runs the default job defined in your configuration.

4.  **Check Output:** Look in your model directories (e.g., `/path/to/your/lora/models`) for generated `.json` metadata files and potentially `.html` preview pages and images, depending on your configuration.

## Core Concepts

Understand how CivitScraper works:

*   **Scanning & Identification**: Finds model files in your specified `input_paths` based on file `patterns`. It calculates a unique hash for each file to identify it on CivitAI.
*   **Metadata**: Fetches detailed information (name, creator, type, base model, tags, ratings, trained words, image URLs, etc.) from the CivitAI API using the file hash. This data is saved locally as `.json` files.
*   **File Organization**: Optionally rearranges your model files (and their associated metadata/images) into a structured directory tree based on metadata. You can choose templates (e.g., organize by type, then creator) or define custom structures. Uses safe `symlink` or `copy` modes by default, or `move` (use with caution!). Includes a `--dry-run` flag for safe testing.
*   **HTML Previews & Gallery**: Generates individual HTML pages for each model, displaying metadata and preview images. Can also create a single `gallery.html` file linking to all individual model pages for easy browsing. It intelligently finds associated images and prioritizes organized files if they exist.
*   **Jobs**: Defines specific tasks in the configuration file (under the `jobs:` section). You can run different jobs to perform different actions (e.g., only fetch metadata, organize files, sync Krita triggers).

## Workflow

This diagram illustrates the typical process flow when running a `scan-paths` job:

```mermaid
graph TD
    A[Start: Run civitscraper] --> B{Load Config};
    B --> C{Select Job(s)};
    C --> D[For each Job (scan-paths type)];
    D --> E[Find Model Files in input_paths];
    E --> F{Filter Files (e.g., skip_existing)};
    F --> G[Batch Files for Processing];
    G --> H[For each File in Batch];
    H --> I[Calculate Hash];
    I --> J{Check Metadata Cache};
    J -- Cache Miss / Stale --> K[Fetch Metadata from CivitAI API];
    J -- Cache Hit --> L[Use Cached Metadata];
    K --> M[Save Metadata (.json)];
    L --> N{Metadata Ready};
    M --> N;
    N --> O{Organization Enabled?};
    O -- Yes --> P[Calculate Target Path];
    P --> Q[Perform File Operation (copy/move/symlink)];
    Q --> R[Process Organized File Path];
    O -- No --> S[Process Original File Path];
    R --> T{Download Images?};
    S --> T;
    T -- Yes --> U[Download Images];
    T -- No --> V{Generate HTML?};
    U --> V;
    V -- Yes --> W[Generate Model HTML];
    V -- No --> X[File Processed];
    W --> X;
    X --> G;  // Loop back for next file in batch
    G -- Batch Complete --> Y{Generate Gallery? (Job Setting)};
    Y -- Yes --> Z[Scan for Model HTMLs (incl. existing/organized)];
    Z --> AA[Create/Update gallery.html];
    Y -- No --> BB[Job Complete];
    AA --> BB;
    BB --> D; // Loop back for next job if any
    D -- All Jobs Done --> CC[End];

    subgraph CivitAI Interaction
        K
    end

    subgraph Local File System Actions
        E
        F
        M
        Q
        U
        W
        Z
        AA
    end

    style K fill:#f9d,stroke:#333,stroke-width:2px
    style Q fill:#ccf,stroke:#333,stroke-width:2px
    style U fill:#ccf,stroke:#333,stroke-width:2px
    style W fill:#ccf,stroke:#333,stroke-width:2px
    style AA fill:#ccf,stroke:#333,stroke-width:2px
```

## Installation

### Requirements

-   Python 3.8 or higher
-   Internet connection for API access

### Installation Steps (Using Virtual Environment - Recommended)

Using a virtual environment keeps dependencies isolated and avoids conflicts with other Python projects.

```bash
# 1. Clone the repository
git clone https://github.com/moonwhaler/civitscraper.git
cd civitscraper

# 2. Create a virtual environment named 'venv'
python -m venv venv

# 3. Activate the virtual environment
# On Windows (cmd/powershell):
venv\Scripts\activate
# On macOS/Linux (bash/zsh):
source venv/bin/activate

# (Your terminal prompt should now show '(venv)' at the beginning)

# 4. Install CivitScraper and its dependencies in editable mode
pip install -e .

# 5. Verify installation
civitscraper --help

# 6. When finished using CivitScraper, deactivate the environment
deactivate
```

## Basic Configuration

CivitScraper uses a YAML configuration file (default: `config/default.yaml`). Start by copying `config/default.yaml.example` or `config/default.yaml.minimal` to `config/default.yaml`.

Here are the essential sections to configure for basic use:

### API Key (Optional)

Providing your CivitAI API key is **optional** for fetching public model data, but **recommended**. Using a key may grant you higher rate limits from the CivitAI API compared to unauthenticated requests.

```yaml
api:
  key: "YOUR_API_KEY_HERE" # Optional: Get from CivitAI account settings
```

### Input Paths

Tell CivitScraper where to find your models. Define one entry under `input_paths` for each type/location.

```yaml
input_paths:
  # Example for LORA models
  lora:
    path: "/mnt/models/Stable-diffusion/loras"  # <--- CHANGE THIS PATH
    type: LORA                         # Identifier used in organization/logging
    patterns: ["*.safetensors", "*.pt"] # File extensions to scan for

  # Example for Checkpoints
  checkpoints:
    path: "/mnt/models/Stable-diffusion/checkpoints" # <--- CHANGE THIS PATH
    type: Checkpoint
    patterns: ["*.safetensors", "*.ckpt"]

  # Add more entries for embeddings, VAEs, etc. as needed
  # embeddings:
  #   path: "/path/to/embeddings"
  #   type: TextualInversion
  #   patterns: ["*.pt", "*.safetensors"]
```

### Output Settings (within a Job)

Control what gets generated. These settings are usually defined *within a specific job* (see [Job System](#job-system)).

```yaml
# Example within a job definition (e.g., 'fetch-all' job)
jobs:
  fetch-all:
    type: scan-paths
    # ... other job settings ...
    output:
      metadata:
        format: "json"                 # Format for metadata files (only json supported)
        path: "{model_dir}"            # Save metadata in the same directory as the model
        filename: "{model_name}.json"  # Filename pattern for metadata
        html:
          enabled: true                # Generate HTML preview pages?
          filename: "{model_name}.html" # Filename pattern for HTML pages
          generate_gallery: true       # Generate a main gallery.html?
          gallery_path: "gallery.html" # Path for the main gallery file (relative to CWD or absolute)
          gallery_title: "Model Gallery" # Title for the gallery page
          include_existing_in_gallery: true # Scan for and include pre-existing HTML cards in the gallery?
      images:
        save: true                     # Download preview images?
        path: "{model_dir}"            # Save images in the same directory as the model
        max_count: 4                   # Max number of images to download per model
        filenames:
          preview: "{model_name}.preview{ext}" # Filename pattern for downloaded images
```

### Organization Settings (within a Job)

Configure how files are organized. Also defined *within a specific job*.

```yaml
# Example within a job definition
jobs:
  fetch-all:
    type: scan-paths
    # ... other job settings ...
    organization:
      enabled: false            # Enable file organization? (Default: false)
      dry_run: false            # Set to true to simulate without moving/copying files
      template: "by_type_and_basemodel" # Choose a predefined structure (see below)
      # custom_template: ""     # Or define your own structure (see Advanced Config)
      output_dir: "{model_dir}/organized" # Base directory for organized files
      operation_mode: "symlink" # How to organize: 'symlink' (recommended), 'copy', or 'move' (use with caution!)
```

> **⚠️ WARNING**: The `move` operation mode permanently changes your original file locations. Use `symlink` or `copy`, or test thoroughly with `dry_run: true` first. Back up your models before enabling organization.

**Common Predefined Templates (`template` setting):**

*   `by_type`: `organized/{type}/...`
*   `by_creator`: `organized/{creator}/...`
*   `by_type_and_creator`: `organized/{type}/{creator}/...`
*   `by_type_and_basemodel`: `organized/{type}/{base_model}/...`
*   *(See [Advanced Configuration](CONFIGURATION.md) for more templates and custom options)*

## Running CivitScraper

Execute CivitScraper from your terminal within the activated virtual environment (`venv`).

### Basic Usage

```bash
# Run the job specified by 'default_job' in your config
civitscraper

# Run a specific job defined in your config
civitscraper --job <job_name>
# Example:
civitscraper -j fetch-all

# Run all defined jobs sequentially
civitscraper --all-jobs

# Use a specific configuration file
civitscraper --config /path/to/your/custom_config.yaml
# Example:
civitscraper -c config/my_settings.yaml
```

### Key Command-Line Arguments

*   `-c, --config FILE`: Path to configuration file (default: `config/default.yaml`).
*   `-j, --job NAME`: Execute only the specified job.
*   `--all-jobs`: Execute all jobs defined in the configuration.
*   `--dry-run`: Simulate file organization (`copy`/`move`/`symlink`) without actually performing the operations. Useful for testing organization templates.
*   `--force-refresh`: Ignore cached API responses and fetch fresh data from CivitAI.
*   `--debug`: Enable verbose debug logging for troubleshooting.
*   `--quiet`: Suppress normal console output (only show errors).

### Examples

```bash
# Run the default job with verbose logging
civitscraper --debug

# Test organization for the 'fetch-loras' job without moving files
civitscraper -j fetch-loras --dry-run

# Force update metadata for all models defined in the 'fetch-all' job
civitscraper -j fetch-all --force-refresh
```

### Convenience Scripts

The project includes wrapper scripts for common actions:

*   **`civitscraper.sh` / `civitscraper.bat`**:
    *   Activates the `venv` virtual environment.
    *   Installs the package (`pip install -e .`) if not already present.
    *   Runs `civitscraper --debug --all-jobs` (executes all configured jobs with debug logging).
*   **`civitscraper-dev.sh` / `civitscraper-dev.bat`**:
    *   Activates the `venv`.
    *   Runs pre-commit checks (`pre-commit run --all-files`).
    *   If checks pass, installs the package and runs `civitscraper --debug --all-jobs`.
    *   If checks fail, it exits with an error.

These scripts provide a quick way to run the scraper or development checks, especially after cloning or pulling updates.

## Key Features (In Detail)

### Scanning & Identification

-   **Discovery**: Finds model files in directories specified in `input_paths` using `patterns`. Can search `recursive`ly.
-   **Hashing**: Computes a BLAKE3 hash for each file to uniquely identify it for CivitAI API lookups.
-   **Filtering**: Can `skip_existing` files that already have a corresponding `.json` metadata file. Can `verify_hashes` against CivitAI data (requires API call).

### Metadata Retrieval

-   Fetches comprehensive data from CivitAI API based on file hash.
-   Includes model details, creator, tags, type, base model, NSFW status, dates, stats (downloads, favorites, ratings), trained words (triggers), and image URLs.
-   **Rating Metrics**: Calculates and stores additional rating metrics:
    -   **`rawRating`**: The original 1-5 rating from CivitAI.
    -   **`weightedRating`**: Confidence-adjusted rating (scales towards neutral 3.0 based on rating/download ratio). Helps balance ratings with low counts.
    -   **`weightedThumbsUp`**: 1-5 rating based on thumbs-up/download ratio (0%=1.0, 5%=2.0, 10%=3.0, 15%=4.0, 20%+=5.0).
-   Saves data as `.json` files alongside models (configurable path/filename).

### Image Downloading

-   Downloads preview images listed in the model's metadata from CivitAI.
-   Configurable via `output.images` within a job:
    -   `save: true` enables downloading.
    -   `path` specifies where to save images (can use placeholders).
    -   `max_count` limits the number of images per model.
    -   `filenames.preview` defines the naming pattern (e.g., `{model_name}.preview{ext}`).

### HTML Preview Generation

-   Generates individual HTML pages for models using Jinja templates.
-   Configurable via `output.metadata.html` within a job:
    -   `enabled: true` turns on generation.
    -   `filename` sets the HTML file name pattern.
-   **Context Building**: The generator gathers necessary data:
    -   Loads metadata from the `.json` file.
    -   Finds associated preview images (looks for downloaded images matching the pattern, checks `images` subdirectories, and potentially uses URLs from metadata if images weren't downloaded).
    -   Includes model details, stats, trained words, generation parameters (if in metadata), etc.
-   **Gallery Generation**:
    -   If `generate_gallery: true`, creates a main gallery page (e.g., `gallery.html`).
    -   `gallery_path` and `gallery_title` configure the gallery file.
    -   If `include_existing_in_gallery: true` (default), it scans configured paths for *any* existing model `.html` files and includes them, providing a view of the entire collection found.
    -   **Organization Awareness**: When building the gallery, if both an original and an organized version of a model's HTML file exist, it prioritizes the organized version.

### File Organization

-   Organizes model files and their associated `.json`, `.html`, and image files based on metadata.
-   Configurable via `organization` within a job:
    -   `enabled: true` activates the feature.
    -   `dry_run: true` simulates changes.
    -   `template` selects a predefined structure (e.g., `by_type_and_basemodel`).
    -   `custom_template` allows defining a custom path structure using placeholders (see [Advanced Configuration](CONFIGURATION.md#available-placeholders)). Placeholders support default values (e.g., `{creator|Unknown}`).
    -   `output_dir` sets the base directory for organized files.
    -   `operation_mode`: `symlink` (creates links, preserves originals), `copy` (duplicates files), `move` (relocates originals - **use carefully!**).

### Job System

-   Define specific tasks (jobs) under the `jobs:` key in the configuration.
-   Each job has a `type` and its own set of configurations (paths, output, organization, etc.).
-   **`scan-paths` type**: The most common type. Scans specified `paths` (referencing keys under `input_paths`), fetches metadata, downloads images, generates HTML, and organizes files based on the job's settings.
-   **`sync-lora-triggers` type**: Specialized job for Krita integration (see below).
-   Run jobs using `civitscraper -j <job_name>` or run the `default_job` with just `civitscraper`.

### Krita AI Diffusion Integration

-   The `sync-lora-triggers` job type helps integrate with Krita AI Diffusion.
-   It scans specified LoRA `paths`, reads their `.json` metadata, and extracts trigger words (`trainedWords` or `activation text`).
-   It then updates Krita's `loras.json` file (path specified by `loras_file` in the job config), matching LoRAs by filename and adding/overwriting their trigger words.
-   This ensures Krita has the correct triggers without manual entry.

```yaml
# Example Job for Krita Sync
jobs:
  sync-triggers:
    type: sync-lora-triggers
    description: "Update Krita loras.json with trigger words"
    recursive: true             # Scan subdirectories for LoRAs?
    loras_file: "/path/to/krita/pykrita/ai_diffusion/loras.json" # <--- CHANGE THIS PATH
    paths: ["lora"]             # Which input_paths entry contains your LoRAs
```

### API Handling (Batching, Caching, etc.)

-   **Batch Processing**: Fetches metadata for multiple files concurrently (`api.batch.max_concurrent`) to speed up processing.
-   **Rate Limiting**: Automatically limits requests per minute (`api.batch.rate_limit`) to avoid hitting CivitAI API limits. Uses a token bucket approach and retries with backoff if limited.
-   **Circuit Breaker**: Temporarily stops requests to specific API endpoints if they repeatedly fail (`api.batch.circuit_breaker`), preventing excessive errors during API outages.
-   **Caching**: Stores API responses locally (`scanner.cache_dir`) to avoid refetching data unnecessarily. Cache duration is configurable (`scanner.cache_validity`). Use `--force-refresh` to bypass the cache.

## Advanced Configuration

For details on advanced settings like API tuning (timeouts, retries, batch controls, circuit breaker), custom organization templates and placeholders, caching specifics, and detailed logging options, please refer to the dedicated **[CONFIGURATION.md](CONFIGURATION.md)** file.

## Troubleshooting

### Common Issues

*   **API Key Issues**: Ensure `api.key` in your config is correct and valid. Check for typos.
*   **Rate Limiting Errors (429)**: If you see frequent rate limit errors in the logs, try reducing `api.batch.rate_limit` (e.g., to `50`) in your config.
*   **File Not Found Errors**: Double-check the `path` settings under `input_paths` in your config. Ensure they point to the correct directories where your models are stored. Check permissions.
*   **Organization Not Working**:
    *   Verify `organization.enabled: true` within the specific job you are running.
    *   Check the `organization.template` or `custom_template` for correctness.
    *   Run with `--dry-run` first to see the planned operations without modifying files. Check the log output.
    *   Ensure the `organization.output_dir` is writable.

### Logging

-   For detailed troubleshooting, run with the `--debug` flag: `civitscraper --debug`
-   Check log files in the directory specified by `logging.file.directory` (default: `logs`). Debug logs provide much more detail about API calls, file processing, and errors.
-   Adjust logging levels in the configuration file (`logging` section) for more or less verbose output to console or file.

## Development

### Testing

CivitScraper uses `pytest`.

```bash
# Install development dependencies (includes pytest, coverage, etc.)
pip install -r requirements-dev.txt

# Run tests
pytest

# Run tests with coverage report
pytest --cov=civitscraper --cov-report=term --cov-report=html
# (HTML report generated in 'htmlcov' directory)
```

### Pre-commit Hooks

Uses `pre-commit` for code formatting (black, isort), linting (flake8), and type checking (mypy).

```bash
# Install pre-commit
pip install pre-commit

# Set up the git hooks
pre-commit install

# Run hooks manually on all files
pre-commit run --all-files
```
Hooks will run automatically on `git commit`.

## License

CivitScraper is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

See the [LICENSE](LICENSE) file for the full text.

**Key implications:**
- You can use, modify, and distribute the software freely.
- If you distribute modified versions (or provide network access to a modified version), you **must** make the modified source code available under the same AGPL-3.0 license.

This project relies on several open-source libraries with compatible licenses (MIT, Apache 2.0, BSD). See the original `readme.md` or `pyproject.toml` for a list.

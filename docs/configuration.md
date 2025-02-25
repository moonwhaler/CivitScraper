# Configuration Reference

Complete reference for CivitScraper configuration options.

## Table of Contents
- [Configuration File Location](#configuration-file-location)
- [Job System](#job-system)
  - [Job Types](#job-types)
  - [Job Templates](#job-templates)
  - [Performance Features](#performance-features)
- [Input Paths](#input-paths)
- [Output Settings](#output-settings)
- [Scanner Settings](#scanner-settings)
- [API Settings](#api-settings)
- [Organization System](#organization-system)
- [Command Line Arguments](#command-line-arguments)
- [Environment Variables](#environment-variables)
- [Logging Settings](#logging-settings)

---

## Configuration File Location

**Priority Order for Configuration Loading:**

CivitScraper loads configuration in the following order (highest to lowest precedence):

1. Environment variable: `CIVITSCAPER_CONFIG`
2. User configuration files:
   - `./civitscaper.yaml`
   - `./civitscaper.yml`
   - `./config/default.yaml`
   - `~/.config/civitscaper/config.yaml`
   - `~/.civitscaper.yaml`

**Configuration Options:**
- Use the default configuration as-is
- Copy and modify the default configuration to one of the user configuration locations
- Create your own configuration file from scratch in any of these locations

---

## Job System

The job system provides a flexible way to define and execute operations with support for templates, parallel execution, and resource optimization. Jobs are the primary way to organize and execute tasks within CivitScraper.

---

### Job Types

#### scan-paths
*Scans directories for model files and processes them*
Scans directories for model files and processes them:
```yaml
jobs:
  fetch-all:
    template: full_process         # Use template (see Job Templates)
    type: scan-paths
    paths: ["lora", "checkpoints"] # Reference input_paths by ID
    recursive: true
    skip_existing: true
    verify_hashes: true
    organize: true                 # Run organization after scanning
```

#### sync-lora-triggers
Synchronizes LoRA trigger words:
```yaml
jobs:
  sync-triggers:
    type: sync-lora-triggers
    paths: ["lora"]               # Paths to scan
    loras_file: "loras.json"      # Trigger definitions file
    recursive: true
```

### Job Templates

The system supports a powerful template inheritance system that allows reusing and extending configurations. Templates help reduce configuration duplication and maintain consistency across jobs:

```yaml
# Define reusable templates
job_templates:
  # Basic scan template
  base_scan:
    type: scan-paths
    recursive: true
    skip_existing: true
    verify_hashes: true

  # Extended template inheriting base settings
  full_process:
    inherit: base_scan             # Inherit from base_scan
    organize: true                 # Add organization
    output:
      metadata:
        format: "json"
        html:
          enabled: true

# Use templates in jobs
jobs:
  fetch-all:
    template: full_process         # Use full processing template
    paths: ["lora", "checkpoints"] # Override specific settings

  fetch-loras:
    template: base_scan           # Use basic scan template
    paths: ["lora"]              # Only process LORA models
```

**Template Features:**
- Inheriting from other templates using `inherit: template_name`
- Overriding inherited values
- Default configurations through the `defaults` section

**Validation Checks:**
- Required fields are present
- Template references exist
- Basic type checking for values

---

### Performance Features

The job system includes several performance optimizations to ensure efficient processing of large model collections:

- **Parallel Execution**:
  - Scan jobs are executed in parallel using asyncio and ThreadPoolExecutor
  - Organization tasks can run in parallel for improved throughput
  - Thread pool automatically scales based on system capabilities

- **Resource Management**:
  - Thread pool optimization with max workers = min(32, CPU_count * 2)
  - Efficient task distribution across available threads
  - Automatic scaling based on system resources

- **Batch Processing**:
  - Dynamic batch sizing optimized for performance:
    - Uses 25% of available CPU cores as scaling factor
    - Base size of 100 items per batch
    - Automatically bounded between 50-500 items
    - Adjusts to total item count to prevent oversized batches
  - Progress tracking for batch operations
  - Failure handling and reporting

## Input Paths

Define paths to scan for models. Each path must have a unique ID that can be referenced in jobs. These paths tell CivitScraper where to look for different types of model files.

```yaml
input_paths:
  lora:  # Path ID
    path: "./models/Lora"
    type: LORA
    recursive: true
    patterns: ["*.safetensors", "*.pt"]

  checkpoints:  # Path ID
    path: "./models/checkpoints"
    type: Checkpoint
    recursive: true
    patterns: ["*.safetensors", "*.ckpt"]
```

## Output Settings

Configure how and where CivitScraper saves metadata and preview images:

```yaml
output:
  metadata:
    path: "{model_dir}"  # Default: same as model
    filename: "{model_name}.json"  # JSON metadata file
    html:
      enabled: true  # Enable HTML generation
      filename: "{model_name}.html"  # HTML output file

  images:
    enabled: true
    path: "{model_dir}/previews"
    max_count: 4
```

**Available Path Variables:**
- `{model_dir}`: Directory containing the model
- `{model_name}`: Model filename without extension
- `{model_type}`: Model type (LORA, Checkpoint, etc.)
- `{base_model}`: Base model name
- `{version}`: Model version

## Scanner Settings

Scanner configuration is split across multiple sections for flexibility. These settings control how CivitScraper processes and validates model files:

### Default Scan Settings
```yaml
defaults:
  scan:
    recursive: true      # Search in subdirectories
    skip_existing: true  # Skip files that already have metadata
    verify_hashes: true  # Verify file hashes against CivitAI data
```

### Per-Path Patterns
File patterns are defined per input path to allow different patterns for different model types:
```yaml
input_paths:
  lora:
    patterns: ["*.safetensors", "*.pt"]  # LORA patterns

  checkpoints:
    patterns: ["*.safetensors", "*.ckpt"]  # Checkpoint patterns

  embeddings:
    patterns: ["*.pt", "*.safetensors"]  # Embedding patterns
```

### Scanner Cache Settings
```yaml
scanner:
  cache_dir: ".civitscaper_cache"  # Cache storage location
  cache_validity: 86400            # Cache lifetime in seconds (24 hours)
  force_refresh: false             # Ignore cache and force refresh
```

The scanner system combines these settings to determine:
- Which files to process (based on path-specific patterns)
- How to process them (recursive, skip existing, verify hashes)
- How to cache results for better performance

## API Settings

Configure API connection parameters and optimization settings:

```yaml
api:
  key: "your-api-key"  # Can also use CIVITAI_API_KEY env var
  base_url: "https://civitai.com/api/v1"
  timeout: 30
  max_retries: 3
  user_agent: "CivitScraper/0.1.0"

  batch:
    enabled: true
    max_concurrent: 4     # Maximum parallel requests
    rate_limit: 100      # Requests/minute
    retry_delay: 2000    # Base delay (ms) for retries
    cache_size: 100      # LRU cache size

    # Circuit breaker prevents API abuse
    circuit_breaker:
      failure_threshold: 5    # Failures before blocking
      reset_timeout: 60       # Seconds until auto-recovery
```

## Organization System

The organization system provides flexible file management with multiple operation modes and template-based path generation. This system helps maintain a clean and organized model collection.

### Configuration

```yaml
organization:
  enabled: true
  template: "by_type"              # Use predefined template
  custom_template: "{base_model}/{type}/{creator}"  # Or custom template
  output_dir: "organized_models"    # Base output directory
  operation_mode: "copy"           # copy, move, or symlink
```

### Operation Modes

- **copy**: Creates copies of files (default)
- **move**: Moves files to new location
- **symlink**: Creates symbolic links
  - On Windows: Requires Administrator privileges
  - On Unix: Uses standard symlink permissions

### Features

- **Collision Detection**:
  - Automatically handles duplicate filenames by adding numeric suffixes
  - Preserves file extensions
  - Maintains original name as base
- **Dry Run Support**:
  - Simulate operations with `--dry-run`
  - Shows planned file operations
  - Validates paths and permissions
- **Metadata Integration**:
  - Generates JSON metadata files
  - Includes model info, ratings, tags
  - Maintains file associations
  - Optional HTML preview generation
  - Preserves metadata during moves
- **Path Sanitization**:
  - Removes problematic characters
  - Ensures valid filesystem paths
  - Handles spaces and special characters
  - Strips leading/trailing dots
- **Windows Support**:
  - Special handling for Windows symlinks
  - Administrator privilege checks
  - Cross-platform path compatibility
  - UNC path support

### Template System

#### Predefined Templates
- `by_type`: `{type}`
- `by_creator`: `{creator}`
- `by_type_and_creator`: `{type}/{creator}`
- `by_base_model`: `{base_model}/{type}`
- `by_nsfw`: `{nsfw}/{type}`
- `by_date`: `{year}/{month}/{type}`
- `by_model_info`: `{model_type}/{model_name}`

#### Template Variables
- **Basic Info**
  - `{type}`: Model type from file path/config
  - `{model_type}`: Model type from API metadata
  - `{model_name}`: Model name from API metadata
  - `{creator}`: Creator username
  - `{base_model}`: Base model name

- **Categorization**
  - `{nsfw}`: NSFW status ("sfw"/"nsfw")

- **Date Information**
  - `{year}`: Creation year
  - `{month}`: Creation month (2-digit)

## Command Line Arguments

**Available Arguments:**
- `-c, --config`: Path to configuration file
- `--dry-run`: Simulate file operations without making changes
  - Shows what files would be organized/copied/moved/created
  - Still performs API calls and metadata processing

## Environment Variables

**Available Variables:**
- `CIVITAI_API_KEY`: Your CivitAI API key
- `CIVITSCAPER_CONFIG`: Path to config file
- `CIVITSCAPER_CACHE_DIR`: Override default cache directory

## Logging Settings

Configure logging behavior and output locations:

```yaml
logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL

  console:
    enabled: true
    level: INFO

  file:
    enabled: true
    level: DEBUG
    directory: logs
    max_size: 10  # Default size in MB
    backup_count: 5
```

Note: Log files are automatically named with timestamps, e.g., civitscaper_20250203_184812.log

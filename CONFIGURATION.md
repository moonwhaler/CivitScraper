# Advanced Configuration

This document details the advanced configuration options for CivitScraper, typically found in your `config/default.yaml` file (or a custom configuration file). For basic setup, refer to the main [README.md](readme.md).

## Table of Contents
- [API Configuration](#api-configuration)
- [Advanced Organization Settings](#advanced-organization-settings)
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
-   **`batch`**: Settings related to processing multiple files concurrently. See [Batch Processing Details](#batch-processing-details).
-   **`circuit_breaker`**: Settings for automatically stopping requests to specific API endpoints if they consistently fail. See [Batch Processing Details](#batch-processing-details).

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

## Scanner Settings (Caching)

The `scanner` section controls caching behavior to reduce redundant API calls.

```yaml
scanner:
  cache_dir: ".civitscraper_cache"  # Directory to store cache files (API responses)
  cache_validity: 86400            # [seconds] How long cache entries are considered valid (default: 24 hours)
  force_refresh: false             # Global flag to ignore cache and always fetch fresh data
```

-   **`cache_dir`**: Specifies the directory where API responses are cached locally.
-   **`cache_validity`**: Determines the maximum age (in seconds) of a cached response before it's considered stale and needs refreshing.
-   **`force_refresh`**: If set to `true` globally (or via the `--force-refresh` command-line flag), the cache will be ignored entirely for the run.

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
    circuit_breaker:
      failure_threshold: 5 # Consecutive failures to trigger breaker
      reset_timeout: 60    # Seconds before retrying a broken circuit
```

-   **`enabled`**: Turns batch processing on or off. If off, requests are made sequentially.
-   **`max_concurrent`**: Limits the number of simultaneous API requests using a semaphore to avoid overwhelming the API or your network.
-   **`rate_limit`**: Uses a token bucket algorithm (per API endpoint) to smooth out requests and stay below the target rate (requests per minute). If the limit is hit, requests will pause and retry with exponential backoff (`retry_delay`).
-   **`cache_size`**: An in-memory LRU cache stores recent API responses during a run to avoid refetching the same data multiple times within that run.
-   **`circuit_breaker`**: Monitors consecutive failures for each API endpoint (e.g., `/models/{id}`, `/images`). If an endpoint fails `failure_threshold` times in a row, the breaker "opens," and further requests to that specific endpoint are blocked for `reset_timeout` seconds to allow the API to recover. This prevents hammering a potentially failing service.

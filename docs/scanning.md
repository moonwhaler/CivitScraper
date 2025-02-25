# Scanning Models

Model scanning is configured through the configuration file and executed via jobs. This system handles the discovery, processing, and metadata retrieval for your model files.

## Table of Contents
- [Configuration](#configuration)
  - [Input Paths](#input-paths)
  - [Scanner Settings](#scanner-settings)
  - [Jobs](#jobs)
- [Advanced Batch Processing](#advanced-batch-processing)
  - [Adaptive Batch Sizing](#1-adaptive-batch-sizing)
  - [Circuit Breaker Protection](#2-circuit-breaker-protection)
  - [Advanced Rate Limiting](#3-advanced-rate-limiting)
  - [Caching System](#4-caching-system)
- [Processing Pipeline](#processing-pipeline)
- [Error Handling and Progress Tracking](#error-handling-and-progress-tracking)

---

## Configuration

### Input Paths

Define paths to scan in your configuration file. Each path can specify different patterns and settings for different model types:

```yaml
input_paths:
  lora:  # Path ID
    path: "./models/Lora"
    type: LORA
    patterns: ["*.safetensors", "*.pt"]

  checkpoints:  # Path ID
    path: "./models/checkpoints"
    type: Checkpoint
    patterns: ["*.safetensors", "*.ckpt"]
```

### Scanner Settings

Configure scanner behavior to control how files are processed and validated:

```yaml
scanner:
  # Enable recursive directory scanning
  recursive: true

  # Skip files that already have metadata
  skip_existing: true

  # Verify file hashes
  verify_hashes: true

  # File patterns to include
  patterns:
    - "*.safetensors"
    - "*.ckpt"
    - "*.pt"
    - "*.pth"

  # File patterns to exclude
  exclude_patterns:
    - "*.tmp"
    - "*.bak"
    - ".DS_Store"
```

### Jobs

Define scanning jobs in your configuration to execute specific scanning operations:

```yaml
jobs:
  fetch-all:
    description: "Fetch metadata for all models"
    actions:
      - type: scan-paths
        paths: ["lora", "checkpoints"]  # Reference input_paths by ID
        recursive: true
        skip_existing: true
        verify_hashes: true
        organize: true  # Run organization after scanning

  update-loras:
    description: "Update LORA metadata"
    actions:
      - type: scan-paths
        paths: ["lora"]  # Only scan LORA path
        recursive: true
        skip_existing: false  # Force update
        verify_hashes: true
```

## Advanced Batch Processing

CivitScraper implements sophisticated batch processing with several advanced features to optimize performance and reliability:

### 1. Adaptive Batch Sizing
*Automatically adjusts batch sizes based on performance metrics*
```yaml
api:
  batch:
    adaptive_batch:
      min_size: 2            # Minimum batch size during poor performance
      max_size: 50           # Maximum batch size during good performance
      scale_up_rate: 0.95    # Success rate threshold to increase batch size
      scale_down_rate: 0.5   # Success rate threshold to decrease batch size
```

The adaptive batch sizing system automatically adjusts batch sizes based on success rates:
- Above 95% success: Increases batch size to improve throughput
- Between 50-95%: Reduces batch size by half
- Below 50%: Reduces batch size to quarter
- Never goes below min_size or above max_size

### 2. Circuit Breaker Protection
*Prevents API abuse and provides graceful degradation during issues*
```yaml
api:
  batch:
    circuit_breaker:
      failure_threshold: 5    # Failures before circuit opens
      reset_timeout: 60       # Seconds before retry
```

The circuit breaker prevents API abuse during outages:
- Tracks failures per endpoint independently
- Opens circuit after failure_threshold is reached
- Auto-recovers after reset_timeout seconds
- Provides graceful degradation during API issues

### 3. Advanced Rate Limiting
*Intelligent request scheduling and throttling*
```yaml
api:
  batch:
    rate_limit: 100      # Requests/minute
    retry_delay: 2000    # Base delay for backoff
```

Features:
- Token bucket implementation per endpoint
- Exponential backoff for retries
- Smart request scheduling
- Automatic request throttling

### 4. Caching System
*Efficient caching for improved performance*
```yaml
api:
  batch:
    cache_size: 100      # LRU cache entries

scanner:
  cache_dir: ".civitscaper_cache"  # Cache directory
  cache_validity: 86400            # Cache validity (24 hours)
  force_refresh: false             # Force cache refresh
```

The caching system provides:
- LRU (Least Recently Used) eviction
- Persistent cache storage
- Configurable validity periods
- Force refresh capability

## Processing Pipeline

The scanning process follows a structured pipeline to ensure efficient and reliable processing:

1. **File Discovery and Validation**:
   - Scans configured input paths for model files
   - Uses patterns defined in input path configuration
   - Recursive scanning based on configuration

2. **Metadata Retrieval and Batch Processing**:
   - Computes file hashes for identification
   - Groups requests into optimally sized batches
   - Implements circuit breaker protection
   - Applies adaptive batch sizing based on performance
   - Enforces rate limits with token bucket algorithm
   - Handles retries with exponential backoff

3. **Metadata Storage**:
   - Saves metadata according to output configuration
   - Supports JSON format
   - Optional HTML generation

---

## Error Handling and Progress Tracking

The scanner provides comprehensive progress information and error tracking to help monitor and troubleshoot operations:

1. **Progress Display**:
   - File scanning progress
   - Hash computation status
   - API request tracking
   - Batch operation progress

2. **Error Tracking**:
   - Hash computation failures
   - API request failures
   - File access issues
   - Invalid file formats
   - Batch operation failures
   - Cache read/write errors

3. **Error Recovery**:
   - Failed operations are logged with timestamps
   - Errors can be retrieved via `get_failures()`
   - Failed items are tracked separately from successful ones
   - Batch operations continue even if some items fail

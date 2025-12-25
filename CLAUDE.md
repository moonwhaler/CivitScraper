# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

### Development Setup
- **Install in development mode**: `pip install -e .` (from project root)
- **Install development dependencies**: `pip install -r requirements-dev.txt`
- **Activate virtual environment**: `source venv/bin/activate` (Linux/macOS)

### Testing
- **Run tests**: `pytest`
- **Run with coverage**: `pytest --cov=civitscraper --cov-report=term --cov-report=html`
- **Coverage report**: Generated in `htmlcov/` directory

### Code Quality
- **Pre-commit hooks**: `pre-commit install` (one-time setup)
- **Run all pre-commit checks**: `pre-commit run --all-files`
- **Format code**: `black .`
- **Sort imports**: `isort --profile black .`
- **Lint code**: `flake8`
- **Type checking**: `mypy civitscraper/`

### Application Commands
- **Run with default job**: `civitscraper`
- **Run specific job**: `civitscraper --job <job_name>`
- **Run all jobs**: `civitscraper --all-jobs`
- **Debug mode**: `civitscraper --debug`
- **Dry run (organization)**: `civitscraper --dry-run`
- **Force refresh cache**: `civitscraper --force-refresh`

### Quick Start Scripts
- **Linux/macOS**: `./civitscraper.sh`
- **Development mode**: `./civitscraper-dev.sh`

## Architecture Overview

CivitScraper is a Python application that fetches metadata from CivitAI for local AI model files and generates HTML previews. The codebase is organized into distinct modules:

### Core Components

**API Layer (`civitscraper/api/`)**:
- `client.py`: Main CivitAI API client with rate limiting and caching
- `rate_limiter.py`: Token bucket rate limiting per endpoint
- `circuit_breaker.py`: Circuit breaker pattern for API resilience
- `endpoints/`: Modular API endpoint implementations (models, versions, images)

**Configuration System (`civitscraper/config/`)**:
- `loader.py`: YAML configuration loading and validation
- Configuration files in `config/` directory (default.yaml)

**Job System (`civitscraper/jobs/`)**:
- `executor.py`: Job orchestration and execution
- Supports multiple job types with configurable workflows

**File Processing (`civitscraper/scanner/`)**:
- `batch_processor.py`: Parallel processing of model files
- `discovery.py`: File discovery with pattern matching
- `file_processor.py`: Individual file processing logic
- `metadata_manager.py`: Metadata fetching and caching
- `image_manager.py`: Image downloading and management
- `html_manager.py`: HTML generation coordination

**HTML Generation (`civitscraper/html/`)**:
- `generator.py`: HTML page generation from templates
- `renderer.py`: Jinja2 template rendering
- `templates/`: HTML templates and static assets (CSS, JS)
- Generates individual model pages and gallery views

**File Organization (`civitscraper/organization/`)**:
- `organizer.py`: File organization with configurable templates
- `path_formatter.py`: Path generation from metadata placeholders
- Supports symlink, copy, and move operations

**Utilities (`civitscraper/utils/`)**:
- `cache.py`: Persistent file-based caching
- `hash.py`: File hashing for model identification (BLAKE3)
- `logging.py`: Configurable logging setup

### Key Design Patterns

- **Batch Processing**: API requests are batched with concurrency control and rate limiting
- **Circuit Breaker**: Prevents API abuse during outages by tracking per-endpoint failures
- **Template System**: Flexible path organization using metadata placeholders
- **Caching Strategy**: Multi-layer caching (in-memory LRU + persistent file cache)

### Configuration Structure

The application uses YAML configuration with these main sections:
- `input_paths`: Define where model files are located
- `jobs`: Define processing workflows (scan-paths, etc.)
- `api`: CivitAI API settings and batch processing configuration
- `organization`: File organization templates and operations
- `logging`: Multi-level logging configuration

### File Processing Flow

1. **Discovery**: Scan input paths for model files matching patterns
2. **Identification**: Generate BLAKE3 hashes for model identification
3. **API Fetching**: Query CivitAI API for metadata using hashes
4. **Metadata Storage**: Save JSON metadata files alongside models
5. **Image Download**: Fetch preview images from CivitAI
6. **HTML Generation**: Create individual model pages and gallery
7. **Organization**: Optionally organize files using metadata templates

### Important Notes

- All file operations support dry-run mode for safety
- The application maintains backwards compatibility with existing metadata files
- HTML generation can be performed independently of API calls when metadata exists
- Pre-commit hooks enforce code quality standards (Black, isort, flake8, mypy, pytest)

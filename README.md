# CivitScraper

A configuration-driven tool for fetching and managing CivitAI model metadata. Easily organize and maintain metadata for your Stable Diffusion models, LoRAs, embeddings, and more.

## Features

- 🔍 **Model Discovery**: Automatically scan configured directories for model files
- 📥 **Metadata Fetching**: Fetch and cache metadata from CivitAI
- 📁 **File Organization**: Organize models using configurable templates
- 🔄 **Trigger Words**: Sync trigger words between model files and loras.json
- 🌐 **HTML Generation**: Create responsive model detail pages
- ⚡ **Batch Processing**: Parallel API requests with caching and rate limiting
- 🛠️ **Configuration-Driven**: All functionality controlled via YAML configuration

## Installation

Requirements:
- Python 3.8 or higher
- git

```bash
# Clone the repository
git clone https://github.com/civitscaper/civitscaper.git
cd civitscaper

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install
pip install .
```

## Quick Usage

```bash
# Run with default configuration
civitscaper

# Run a specific job
civitscaper -j fetch-all

# Run with a custom configuration file
civitscaper -c path/to/config.yaml
```

## Quick Start

1. CivitScraper ships with a default configuration file in `config/default.yaml`. You can either:
   - Use the default configuration as-is
   - Copy and modify it to one of the user configuration locations (see below)
   - Create your own configuration file from scratch

Here's an example of a basic configuration:

```yaml
# Input paths to scan for models
input_paths:
  lora:
    path: "./models/Lora"
    type: LORA
    patterns: ["*.safetensors", "*.pt"]
  checkpoints:
    path: "./models/Stable-diffusion"
    type: Checkpoint
    patterns: ["*.safetensors", "*.ckpt"]

# Define jobs
jobs:
  fetch-all:
    description: "Fetch metadata for all models"
    type: scan-paths
    paths: ["lora", "checkpoints"]
    recursive: true
    skip_existing: true
    verify_hashes: true
    organize: true  # Organize after scanning
```

2. Run CivitScraper:

```bash
# Configuration is loaded from the following locations (in order of precedence):
# 1. CIVITSCAPER_CONFIG environment variable
# 2. User configuration files:
#    - ./civitscaper.yaml
#    - ./civitscaper.yml
#    - ./config/default.yaml
#    - ~/.config/civitscaper/config.yaml
#    - ~/.civitscaper.yaml
# 3. Default configuration:
#    - ./config/default.yaml (ships with the project)
civitscaper

# You can also set the config path via environment variable:
CIVITSCAPER_CONFIG=path/to/config.yaml civitscaper

# Or specify a job to run:
civitscaper -j fetch-all
```

## Configuration

CivitScraper is highly configurable through YAML configuration files. The configuration controls:

- Input paths to scan for models
- API settings for connecting to CivitAI
- Output settings for metadata and images
- Organization templates for file management
- Job definitions for executing tasks

See the [Configuration Reference](docs/configuration.md) for complete details.

## HTML Generation

CivitScraper can generate detailed HTML pages for your models with:

- Responsive design that works on all devices
- Model information (name, type, creator, stats)
- Image gallery with fullscreen support
- Prompt display with copy-to-clipboard functionality
- File details and download options

See the [HTML Generation](docs/html-generator.md) documentation for more information.

## File Organization

The organization system provides flexible file management with:

- Multiple operation modes (copy, move, symlink)
- Template-based path generation
- Predefined templates for common organization schemes
- Custom templates with variables

See the [File Organization](docs/organization.md) documentation for details.

## Command-Line Interface

```
usage: civitscaper [-h] [-c CONFIG] [-j JOB] [--all-jobs] [--dry-run] [--debug] [--quiet]

CivitScraper - A tool for fetching and managing CivitAI model metadata

options:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        Path to configuration file
  -j JOB, --job JOB     Execute a specific job
  --all-jobs            Execute all jobs
  --dry-run             Simulate file operations without making changes
  --debug               Enable debug logging
  --quiet               Suppress console output
```

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).

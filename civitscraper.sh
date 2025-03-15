#!/bin/bash

# Activate virtual environment
source venv/bin/activate

# DEV command to do pre-commit checks
# pre-commit run --all-files

# Install newer version, if source has changed
pip install -e .

# Start with debug enabled - and executing
# all available jobs configured
civitscraper --debug --all-jobs

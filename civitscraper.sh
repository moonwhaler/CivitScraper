#!/bin/bash

# Activate virtual environment
source venv/bin/activate

# Install package if not already installed
if ! pip show civitscraper > /dev/null 2>&1; then
    pip install -e .
fi

# Start with debug enabled - and executing
# all available jobs configured
civitscraper --debug --all-jobs

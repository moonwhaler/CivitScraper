#!/bin/bash

# Activate virtual environment
source venv/bin/activate

# Do pre-commit checks
if pre-commit run --all-files; then
    # Only execute if pre-commit was successful
    pip install -e .
    civitscraper --debug --all-jobs
else
    echo "Pre-commit checks failed. Please fix the issues before proceeding."
    exit 1
fi

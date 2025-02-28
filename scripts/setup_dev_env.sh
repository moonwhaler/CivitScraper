#!/bin/bash
# Setup development environment for CivitScraper
# This script installs development dependencies and pre-commit hooks

set -e

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo "Error: This script must be run from the root directory of the CivitScraper project."
    exit 1
fi

echo "Setting up development environment for CivitScraper..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install development dependencies
echo "Installing development dependencies..."
pip install -r requirements-dev.txt

# Install the package in development mode
echo "Installing CivitScraper in development mode..."
pip install -e .

# Install pre-commit hooks
echo "Installing pre-commit hooks..."
pre-commit install

echo "Development environment setup complete!"
echo "You can now run tests with 'pytest' and pre-commit hooks with 'pre-commit run --all-files'"
echo "To activate the virtual environment in the future, run 'source venv/bin/activate'"

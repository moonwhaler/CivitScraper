@echo off
REM Setup development environment for CivitScraper
REM This script installs development dependencies and pre-commit hooks

REM Check if we're in the right directory
if not exist "pyproject.toml" (
    echo Error: This script must be run from the root directory of the CivitScraper project.
    exit /b 1
)

echo Setting up development environment for CivitScraper...

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install development dependencies
echo Installing development dependencies...
pip install -r requirements-dev.txt

REM Install the package in development mode
echo Installing CivitScraper in development mode...
pip install -e .

REM Install pre-commit hooks
echo Installing pre-commit hooks...
pre-commit install

echo Development environment setup complete!
echo You can now run tests with 'pytest' and pre-commit hooks with 'pre-commit run --all-files'
echo To activate the virtual environment in the future, run 'venv\Scripts\activate.bat'

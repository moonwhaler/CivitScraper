@echo off
REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install package if not already installed
pip show civitscraper >nul 2>&1
if errorlevel 1 (
    pip install -e .
)

REM Start with debug enabled - and executing all available jobs
civitscraper

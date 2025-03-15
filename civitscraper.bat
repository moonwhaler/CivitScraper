@echo off
REM Activate virtual environment
call venv\Scripts\activate.bat

REM DEV command to do pre-commit checks
REM pre-commit run --all-files

REM Install newer version, if source has changed
pip install -e .

REM Start with debug enabled - and executing all available jobs
civitscraper --debug --all-jobs

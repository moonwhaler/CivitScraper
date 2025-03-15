@echo off

:: Activate virtual environment
call venv\Scripts\activate.bat

:: Do pre-commit checks
pre-commit run --all-files
if %ERRORLEVEL% EQU 0 (
    :: Only execute if pre-commit was successful
    pip install -e .
    civitscraper --debug --all-jobs
) else (
    echo Pre-commit checks failed. Please fix the issues before proceeding.
    exit /b 1
)

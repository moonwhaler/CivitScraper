"""
Pytest configuration and shared fixtures.

This module contains shared fixtures and configuration for the test suite.
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Generator

import pytest
import yaml


@pytest.fixture
def sample_config() -> Dict[str, Any]:
    """
    Return a sample configuration dictionary for testing.

    Returns:
        Dict[str, Any]: A sample configuration dictionary
    """
    return {
        "api": {
            "key": "test_api_key",
            "base_url": "https://civitai.com/api/v1",
            "timeout": 30,
            "max_retries": 3,
            "user_agent": "CivitScraper-Test/0.1.0",
            "batch": {
                "enabled": True,
                "max_concurrent": 2,
                "rate_limit": 100,
                "retry_delay": 1000,
                "cache_size": 10,
                "circuit_breaker": {"failure_threshold": 5, "reset_timeout": 60},
            },
        },
        "scanner": {"cache_dir": ".test_cache", "cache_validity": 3600, "force_refresh": False},
        "output": {
            "metadata": {
                "format": "json",
                "path": "{model_dir}",
                "filename": "{model_name}.json",
                "html": {"enabled": True, "filename": "{model_name}.html"},
            },
            "images": {
                "save": True,
                "path": "{model_dir}",
                "max_count": 2,
                "filenames": {"preview": "{model_name}.preview{ext}"},
            },
        },
        "input_paths": {
            "test_path": {"path": "/test/path", "type": "LORA", "patterns": ["*.safetensors"]}
        },
        "jobs": {
            "test_job": {
                "type": "scan-paths",
                "paths": ["test_path"],
                "recursive": True,
                "skip_existing": True,
                "verify_hashes": True,
                "organize": False,
            }
        },
    }


@pytest.fixture
def config_file(sample_config: Dict[str, Any]) -> Generator[str, None, None]:
    """
    Create a temporary config file with the sample configuration.

    Args:
        sample_config: The sample configuration dictionary

    Yields:
        str: Path to the temporary config file
    """
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="wb") as temp_file:
        yaml_content = yaml.dump(sample_config)
        temp_file.write(yaml_content.encode("utf-8"))
        temp_file_path = temp_file.name

    yield temp_file_path

    # Clean up
    if os.path.exists(temp_file_path):
        os.unlink(temp_file_path)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """
    Create a temporary directory for testing.

    Yields:
        Path: Path to the temporary directory
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)

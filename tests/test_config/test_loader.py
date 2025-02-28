"""
Tests for the configuration loader.

This module contains tests for the configuration loading and validation functionality.
"""

import os
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from civitscraper.config.loader import load_and_validate_config


def test_load_config_with_valid_file(config_file: str, sample_config: Dict[str, Any]):
    """
    Test loading a valid configuration file.

    Args:
        config_file: Path to a temporary config file
        sample_config: The expected configuration dictionary
    """
    # Load the config
    config = load_and_validate_config(config_file)

    # Verify the config was loaded correctly
    assert config["api"]["key"] == sample_config["api"]["key"]
    assert config["api"]["base_url"] == sample_config["api"]["base_url"]
    assert config["scanner"]["cache_dir"] == sample_config["scanner"]["cache_dir"]


def test_load_config_with_environment_variable(config_file: str, monkeypatch):
    """
    Test loading a configuration with an API key from an environment variable.

    Args:
        config_file: Path to a temporary config file
        monkeypatch: Pytest fixture for patching environment variables
    """
    # Set the environment variable
    monkeypatch.setenv("CIVITAI_API_KEY", "env_api_key")

    # Load the config
    config = load_and_validate_config(config_file)

    # Verify the API key was loaded from the environment variable
    assert config["api"]["key"] == "env_api_key"


def test_load_config_with_nonexistent_file():
    """Test loading a configuration with a nonexistent file."""
    # Try to load a nonexistent config file
    with pytest.raises(FileNotFoundError):
        load_and_validate_config("nonexistent_config.yaml")


def test_load_config_with_invalid_yaml(temp_dir: Path):
    """
    Test loading a configuration with invalid YAML.

    Args:
        temp_dir: Path to a temporary directory
    """
    # Create an invalid YAML file
    invalid_yaml_file = temp_dir / "invalid.yaml"
    invalid_yaml_file.write_text("invalid: yaml: content:")

    # Try to load the invalid config file
    with pytest.raises(yaml.YAMLError):
        load_and_validate_config(str(invalid_yaml_file))


def test_load_config_with_default_values(temp_dir: Path):
    """
    Test loading a configuration with default values.

    Args:
        temp_dir: Path to a temporary directory
    """
    # Create a minimal config file
    minimal_config_file = temp_dir / "minimal.yaml"
    minimal_config_file.write_text(
        """
    api:
      key: "minimal_api_key"
      base_url: "https://civitai.com/api/v1"
    input_paths:
      test_path:
        path: "/test/path"
        type: "LORA"
        patterns: ["*.safetensors"]
    """
    )

    # Load the config
    config = load_and_validate_config(str(minimal_config_file))

    # Verify default values were applied
    assert config["api"]["key"] == "minimal_api_key"
    assert config["api"]["base_url"] == "https://civitai.com/api/v1"
    assert "timeout" in config["api"]  # Default value should be present

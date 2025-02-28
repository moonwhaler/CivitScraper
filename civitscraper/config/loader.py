"""
Configuration loader for CivitScraper.

This module handles loading configuration from various sources:
1. Environment variable: CIVITSCRAPER_CONFIG
2. User configuration files
3. Default configuration
"""

import logging
import os
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "./config/default.yaml"
USER_CONFIG_PATHS = [
    "./civitscraper.yaml",
    "./civitscraper.yml",
    "./config/default.yaml",
    os.path.expanduser("~/.config/civitscraper/config.yaml"),
    os.path.expanduser("~/.civitscraper.yaml"),
]


def load_yaml_config(path: str) -> Dict[str, Any]:
    """
    Load a YAML configuration file.

    Args:
        path: Path to the YAML file

    Returns:
        Dict containing the configuration

    Raises:
        FileNotFoundError: If the file doesn't exist
        yaml.YAMLError: If the file is not valid YAML
    """
    try:
        with open(path, "r") as f:
            config = yaml.safe_load(f)
        logger.info(f"Loaded configuration from {path}")
        # Ensure we always return a dictionary
        if config is None:
            return {}
        if not isinstance(config, dict):
            logger.warning(
                f"Configuration from {path} is not a dictionary, converting to empty dict"
            )
            return {}
        return config
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {path}")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration: {e}")
        raise


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from various sources.

    Priority order:
    1. Specified config_path parameter
    2. Environment variable: CIVITSCRAPER_CONFIG
    3. User configuration files
    4. Default configuration

    Args:
        config_path: Optional path to configuration file

    Returns:
        Dict containing the configuration

    Raises:
        FileNotFoundError: If no configuration file is found or if the specified file doesn't exist
    """
    # Check specified config path
    if config_path:
        if os.path.exists(config_path):
            return load_yaml_config(config_path)
        else:
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

    # Check environment variable
    env_config_path = os.environ.get("CIVITSCRAPER_CONFIG")
    if env_config_path and os.path.exists(env_config_path):
        return load_yaml_config(env_config_path)

    # Check user configuration paths
    for path in USER_CONFIG_PATHS:
        if os.path.exists(path):
            return load_yaml_config(path)

    # Fall back to default configuration
    if os.path.exists(DEFAULT_CONFIG_PATH):
        return load_yaml_config(DEFAULT_CONFIG_PATH)

    # No configuration found
    raise FileNotFoundError("No configuration file found")


def merge_configs(base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge two configurations.

    Args:
        base_config: Base configuration
        override_config: Configuration to override base

    Returns:
        Merged configuration
    """
    result = base_config.copy()

    for key, value in override_config.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value

    return result


def validate_config(config: Dict[str, Any]) -> bool:
    """
    Validate configuration structure and required fields.

    Args:
        config: Configuration to validate

    Returns:
        True if configuration is valid, False otherwise
    """
    # Check required top-level sections
    required_sections = ["input_paths", "api"]
    for section in required_sections:
        if section not in config:
            logger.error(f"Missing required configuration section: {section}")
            return False

    # Check input paths
    if not config["input_paths"]:
        logger.error("No input paths defined")
        return False

    for path_id, path_config in config["input_paths"].items():
        if "path" not in path_config:
            logger.error(f"Missing 'path' in input path {path_id}")
            return False
        if "type" not in path_config:
            logger.error(f"Missing 'type' in input path {path_id}")
            return False
        if "patterns" not in path_config:
            logger.error(f"Missing 'patterns' in input path {path_id}")
            return False

    # Check API configuration
    if "base_url" not in config["api"]:
        logger.error("Missing 'base_url' in API configuration")
        return False

    return True


def load_and_validate_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load and validate configuration.

    Args:
        config_path: Optional path to configuration file

    Returns:
        Validated configuration

    Raises:
        ValueError: If configuration is invalid
    """
    config = load_config(config_path)

    # Apply default values
    default_config = {}
    if os.path.exists(DEFAULT_CONFIG_PATH):
        try:
            default_config = load_yaml_config(DEFAULT_CONFIG_PATH)
        except Exception as e:
            logger.warning(f"Failed to load default configuration: {e}")

    # Apply default API values if they don't exist in the loaded config
    if "api" in default_config and "api" in config:
        for key, value in default_config["api"].items():
            if key not in config["api"]:
                config["api"][key] = value

    # Apply environment variable overrides
    if "CIVITAI_API_KEY" in os.environ:
        if "api" not in config:
            config["api"] = {}
        config["api"]["key"] = os.environ["CIVITAI_API_KEY"]

    if not validate_config(config):
        raise ValueError("Invalid configuration")

    return config

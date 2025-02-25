"""
Configuration loader for CivitScraper.

This module handles loading configuration from various sources:
1. Environment variable: CIVITSCAPER_CONFIG
2. User configuration files
3. Default configuration
"""

import os
import yaml
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "./config/default.yaml"
USER_CONFIG_PATHS = [
    "./civitscaper.yaml",
    "./civitscaper.yml",
    "./config/default.yaml",
    os.path.expanduser("~/.config/civitscaper/config.yaml"),
    os.path.expanduser("~/.civitscaper.yaml"),
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
    2. Environment variable: CIVITSCAPER_CONFIG
    3. User configuration files
    4. Default configuration
    
    Args:
        config_path: Optional path to configuration file
        
    Returns:
        Dict containing the configuration
        
    Raises:
        FileNotFoundError: If no configuration file is found
    """
    # Check specified config path
    if config_path and os.path.exists(config_path):
        return load_yaml_config(config_path)
    
    # Check environment variable
    env_config_path = os.environ.get("CIVITSCAPER_CONFIG")
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


def resolve_inheritance(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve inheritance in job templates and jobs.
    
    Args:
        config: Configuration with inheritance references
        
    Returns:
        Configuration with resolved inheritance
    """
    # Resolve job template inheritance
    if "job_templates" in config:
        for template_name, template in config["job_templates"].items():
            if "inherit" in template:
                parent_name = template.pop("inherit")
                parent_path = parent_name.split(".")
                
                # Find parent template
                parent = config
                for part in parent_path:
                    if part not in parent:
                        logger.warning(f"Parent template {parent_name} not found for {template_name}")
                        break
                    parent = parent[part]
                
                # Merge parent and child
                if isinstance(parent, dict):
                    config["job_templates"][template_name] = merge_configs(parent, template)
    
    # Resolve job inheritance
    if "jobs" in config:
        for job_name, job in config["jobs"].items():
            if "template" in job:
                template_name = job.pop("template")
                
                # Find template
                if "job_templates" in config and template_name in config["job_templates"]:
                    template = config["job_templates"][template_name]
                    config["jobs"][job_name] = merge_configs(template, job)
                else:
                    logger.warning(f"Template {template_name} not found for job {job_name}")
    
    return config


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
    Load, resolve inheritance, and validate configuration.
    
    Args:
        config_path: Optional path to configuration file
        
    Returns:
        Validated configuration
        
    Raises:
        ValueError: If configuration is invalid
    """
    config = load_config(config_path)
    config = resolve_inheritance(config)
    
    if not validate_config(config):
        raise ValueError("Invalid configuration")
    
    return config

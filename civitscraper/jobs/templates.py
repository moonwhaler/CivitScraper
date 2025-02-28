"""
Job templates for CivitScraper.

This module defines the job templates for common tasks.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Default job templates
DEFAULT_JOB_TEMPLATES = {
    # Basic scan without organization
    "base_scan": {
        "type": "scan-paths",
        "recursive": True,
        "skip_existing": True,
        "verify_hashes": True,
        "organize": False,
        "output": {
            "metadata": {
                "format": "json",
                "path": "{model_dir}",
                "filename": "{model_name}.json",
                "html": {
                    "enabled": True,
                    "filename": "{model_name}.html",
                },
            },
            "images": {
                "save": True,
                "path": "{model_dir}",
                "max_count": 4,
                "filenames": {
                    "preview": "{model_name}.preview{ext}",
                },
            },
        },
    },
    # Full processing with organization
    "full_process": {
        "type": "scan-paths",
        "inherit": "base_scan",
        "organize": True,
        "output": {
            "metadata": {
                "format": "json",
                "path": "{model_dir}",
                "filename": "{model_name}.json",
                "html": {
                    "enabled": True,
                    "filename": "{model_name}.html",
                },
            },
            "images": {
                "save": True,
                "path": "{model_dir}",
                "max_count": 4,
                "filenames": {
                    "preview": "{model_name}.preview{ext}",
                },
            },
        },
    },
    # Metadata-only template
    "metadata_only": {
        "type": "scan-paths",
        "inherit": "base_scan",
        "output": {
            "metadata": {
                "format": "json",
                "path": "{model_dir}",
                "filename": "{model_name}.json",
                "html": {
                    "enabled": False,
                },
            },
            "images": {
                "save": False,
            },
        },
    },
    # Trigger word synchronization template
    "sync_triggers": {
        "type": "sync-lora-triggers",
        "description": "Synchronize LoRA trigger words",
        "recursive": True,
        "loras_file": "loras.json",
        "paths": [],  # Empty array as default, should be overridden when creating a job
    },
    # Gallery generation template
    "generate_gallery": {
        "type": "scan-paths",
        "inherit": "base_scan",
        "generate_gallery": True,
        "gallery_path": "gallery.html",
        "gallery_title": "Model Gallery",
    },
}


def get_job_template(template_name: str) -> Optional[Dict[str, Any]]:
    """
    Get a job template.

    Args:
        template_name: Template name

    Returns:
        Template or None if not found
    """
    template = DEFAULT_JOB_TEMPLATES.get(template_name)
    if template is not None and isinstance(template, dict):
        # Ensure we're returning a properly typed dictionary
        result: Dict[str, Any] = {}
        for k, v in template.items():
            result[k] = v
        return result
    return None


def get_all_job_templates() -> Dict[str, Dict[str, Any]]:
    """
    Get all job templates.

    Returns:
        Dictionary of template name -> template
    """
    # Create a deep copy to ensure proper typing
    templates: Dict[str, Dict[str, Any]] = {}
    for name, template in DEFAULT_JOB_TEMPLATES.items():
        if isinstance(template, dict):
            # Ensure we're creating a properly typed dictionary
            result: Dict[str, Any] = {}
            for k, v in template.items():
                result[k] = v
            templates[name] = result
    return templates


def create_job_from_template(template_name: str, **kwargs) -> Optional[Dict[str, Any]]:
    """
    Create a job from a template.

    Args:
        template_name: Template name
        **kwargs: Template overrides

    Returns:
        Job or None if template not found
    """
    # Get template
    template = get_job_template(template_name)
    if not template:
        logger.error(f"Template not found: {template_name}")
        return None

    # Create job
    job: Dict[str, Any] = template.copy()

    # Apply overrides
    for key, value in kwargs.items():
        if isinstance(value, dict) and key in job and isinstance(job[key], dict):
            # Merge dictionaries
            job[key] = {**job[key], **value}
        else:
            # Override value
            job[key] = value

    return job

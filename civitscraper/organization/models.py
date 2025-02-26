"""
Data models for file organization.

This module contains data models used by the file organization feature.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class OrganizationResult:
    """Result of a file organization operation."""
    source_path: str
    target_path: Optional[str] = None
    success: bool = False
    error: Optional[str] = None

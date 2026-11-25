"""
File organizer for CivitScraper.

This module handles organizing model files based on metadata.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from ..scanner.discovery import get_html_path, get_image_path, get_metadata_path, is_within
from .config import OrganizationConfig
from .operations import FileOperationHandler
from .path_formatter import PathFormatter

logger = logging.getLogger(__name__)


def _same_path(a: str, b: str) -> bool:
    """Compare two paths after normalization (case-insensitive on Windows)."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


DEFAULT_OUTPUT_DIR = "{model_dir}/organized"


def _path_parts(path: str) -> List[str]:
    """Split a path into normalized components, accepting forward and back slashes."""
    normalized = os.path.normcase(path).replace("\\", "/")
    return [part for part in normalized.split("/") if part and part != "."]


def is_in_organized_output(
    file_path: str, org_config: OrganizationConfig, config: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Check whether a file already lives inside the organization output.

    For ``{model_dir}/<suffix>`` output dirs (default ``{model_dir}/organized``) the
    suffix components are searched in the file's directory *below its input root*,
    so a library that itself lives under e.g. ``/data/organized/`` is not mistaken
    for organized output. For an absolute output dir, real path containment is used.

    Args:
        file_path: Path to a model (or related) file
        org_config: Organization configuration
        config: Full configuration (for ``input_paths``)

    Returns:
        True if the file is inside an organization output directory
    """
    output_dir = org_config.output_dir or DEFAULT_OUTPUT_DIR

    if "{model_dir}" not in output_dir:
        return is_within(file_path, os.path.expanduser(output_dir))

    suffix = _path_parts(output_dir.split("{model_dir}", 1)[1])
    if not suffix or any("{" in part for part in suffix):
        # Organizing into the model dir itself (or an unresolvable template):
        # there is no distinguishable output subtree.
        return False

    file_dir = os.path.dirname(os.path.abspath(file_path))
    root = _containing_input_root(file_dir, config)
    if root is None:
        return False
    return _suffix_index(os.path.relpath(file_dir, root), suffix) is not None


def organized_output_root(model_dir: str, org_config: OrganizationConfig) -> str:
    """Return the organization output directory for models in ``model_dir``."""
    output_dir = org_config.output_dir or DEFAULT_OUTPUT_DIR
    return os.path.expanduser(output_dir.replace("{model_dir}", model_dir))


def _containing_input_root(path: str, config: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return the most specific configured input root containing ``path``."""
    roots = [
        os.path.abspath(os.path.expanduser(pc["path"]))
        for pc in (config or {}).get("input_paths", {}).values()
        if isinstance(pc, dict) and isinstance(pc.get("path"), str)
    ]
    containing = [root for root in roots if is_within(path, root)]
    return max(containing, key=len) if containing else None


def _suffix_index(rel_dir: str, suffix: List[str]) -> Optional[int]:
    """Index of the first occurrence of ``suffix`` in ``rel_dir``'s components."""
    parts = _path_parts(rel_dir)
    width = len(suffix)
    for i in range(len(parts) - width + 1):
        if parts[i : i + width] == suffix:
            return i
    return None


def original_dir_for(
    organized_dir: str, org_config: OrganizationConfig, config: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Map a directory inside ``{model_dir}/<suffix>`` output back to ``{model_dir}``.

    Returns None for absolute output dirs (the source location is not derivable)
    or when the directory is not inside organization output.
    """
    output_dir = org_config.output_dir or DEFAULT_OUTPUT_DIR
    if "{model_dir}" not in output_dir:
        return None
    suffix = _path_parts(output_dir.split("{model_dir}", 1)[1])
    if not suffix:
        return None

    organized_dir = os.path.abspath(organized_dir)
    root = _containing_input_root(organized_dir, config)
    if root is None:
        return None
    rel_dir = os.path.relpath(organized_dir, root)
    index = _suffix_index(rel_dir, suffix)
    if index is None:
        return None
    raw_parts = [p for p in rel_dir.replace("\\", "/").split("/") if p and p != "."]
    return os.path.join(root, *raw_parts[:index])


class FileOrganizer:
    """
    Organizer for model files.

    This class coordinates the organization of model files based on metadata.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize file organizer.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.org_config = OrganizationConfig.from_dict(config)
        self.path_formatter = PathFormatter()
        self.file_handler = FileOperationHandler(config)
        self.dry_run = config.get("dry_run", False)

    def get_target_path(self, file_path: str, metadata: Dict[str, Any]) -> Optional[str]:
        """
        Calculate target path for a file without performing operations.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            Target path or None if calculation failed
        """
        try:
            template = self.path_formatter.get_template(
                self.org_config.template, self.org_config.custom_template
            )

            output_dir = self.org_config.output_dir
            if not output_dir:
                # Use default output directory
                output_dir = DEFAULT_OUTPUT_DIR
                logger.debug(
                    f"Using default output directory '{output_dir}' because none was specified"
                )

            output_dir = output_dir.replace("{model_dir}", os.path.dirname(file_path))

            relative_path = self.path_formatter.format_path(template, metadata)

            target_dir = os.path.join(output_dir, relative_path)
            target_path = os.path.join(target_dir, os.path.basename(file_path))

            return target_path

        except Exception as e:
            logger.error(f"Error calculating target path for {file_path}: {e}")
            return None

    def should_process_file(self, file_path: str) -> bool:
        """
        Determine if a file should be processed based on existence.

        Args:
            file_path: Path to file

        Returns:
            True if file exists and should be processed, False otherwise
        """
        return os.path.exists(file_path)

    def organize_file(self, file_path: str, metadata: Dict[str, Any]) -> Optional[str]:
        """
        Organize a model file.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            Path to organized file or None if organization failed
        """
        if not self.org_config.enabled:
            logger.debug("Organization is disabled")
            return None

        try:
            if is_in_organized_output(file_path, self.org_config, self.config):
                # Already organized (e.g. moved on an earlier run). Re-organizing
                # would nest it one level deeper on every run.
                logger.debug(f"Already in organization output, leaving in place: {file_path}")
                return file_path

            target_path = self.get_target_path(file_path, metadata)
            if not target_path:
                return None

            if _same_path(file_path, target_path):
                return file_path

            if os.path.exists(target_path):
                logger.warning(
                    f"Target path already exists: {target_path}. It will be overwritten if needed."
                )

            # Only process pre-existing files
            if self.should_process_file(file_path):
                related_files = self.file_handler.get_related_files(file_path)
                success = self.file_handler.perform_operation(
                    source_path=file_path,
                    target_path=target_path,
                    operation_type=self.org_config.operation_mode,
                    on_collision=self.org_config.on_collision,
                    dry_run=self.dry_run,
                )
                if not success:
                    # If the main file operation failed (e.g., skipped, failed on collision),
                    # we don't proceed with related files and return None for the target path.
                    return None

                # Process related files that exist. Each target is computed with the
                # same path rules used to find it, so central (base_dir) sidecars and
                # custom templates map consistently and never get mangled paths.
                for related_path, file_type, preview_index in related_files:
                    if self.should_process_file(related_path):
                        related_target_path = self._related_target_path(
                            target_path, related_path, file_type, preview_index
                        )
                        if _same_path(related_path, related_target_path):
                            logger.debug(f"Related file already in place: {related_path}")
                            continue

                        self.file_handler.perform_operation(
                            source_path=related_path,
                            target_path=related_target_path,
                            operation_type=self.org_config.operation_mode,
                            on_collision=self.org_config.on_collision,
                            dry_run=self.dry_run,
                        )

            return target_path

        except Exception as e:
            logger.error(f"Error organizing {file_path}: {e}")
            return None

    def _related_target_path(
        self,
        target_path: str,
        related_path: str,
        file_type: str,
        preview_index: Optional[int],
    ) -> str:
        """Compute where a related file belongs once the model lives at target_path."""
        if file_type == "metadata":
            return get_metadata_path(target_path, self.config)
        if file_type == "html":
            return get_html_path(target_path, self.config)
        ext = os.path.splitext(related_path)[1]
        return get_image_path(target_path, self.config, f"preview{preview_index}", ext)

    def get_target_paths(
        self,
        file_paths: List[str],
        metadata_dict: Dict[str, Dict[str, Any]],
    ) -> Dict[str, str]:
        """
        Get target paths for files without performing operations.

        Args:
            file_paths: List of file paths
            metadata_dict: Dictionary of file path -> metadata

        Returns:
            Dictionary mapping source paths to target paths
        """
        if not self.org_config.enabled:
            logger.debug("Organization is disabled")
            return {}

        target_paths = {}

        for file_path in file_paths:
            metadata = metadata_dict.get(file_path)
            if not metadata:
                logger.warning(f"No metadata found for {file_path}")
                continue

            target_path = self.get_target_path(file_path, metadata)
            if target_path:
                target_paths[file_path] = target_path

        return target_paths

    def organize_files(
        self,
        file_paths: List[str],
        metadata_dict: Dict[str, Dict[str, Any]],
    ) -> List[Tuple[str, Optional[str]]]:
        """
        Organize multiple model files.

        Args:
            file_paths: List of file paths
            metadata_dict: Dictionary of file path -> metadata

        Returns:
            List of (file_path, target_path) tuples
        """
        if not self.org_config.enabled:
            logger.debug("Organization is disabled")
            return [(file_path, None) for file_path in file_paths]

        results: List[Tuple[str, Optional[str]]] = []

        for file_path in file_paths:
            metadata = metadata_dict.get(file_path)
            if not metadata:
                logger.warning(f"No metadata found for {file_path}")
                results.append((file_path, None))
                continue

            target_path = self.organize_file(file_path, metadata)

            results.append((file_path, target_path))

        return results

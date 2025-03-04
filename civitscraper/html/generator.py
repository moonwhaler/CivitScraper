"""
HTML generator for CivitScraper.

This module handles generating HTML pages for models using Jinja templates.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from ..scanner.discovery import find_html_files
from .context import ContextBuilder
from .paths import PathManager
from .renderer import TemplateRenderer

logger = logging.getLogger(__name__)


class HTMLGenerator:
    """
    Generator for HTML pages.

    This class orchestrates the HTML generation process using the various
    components for path management, template rendering, context preparation,
    image handling, and data sanitization.
    """

    def __init__(
        self, config: Dict[str, Any], template_dir: Optional[str] = None, model_processor=None
    ):
        """
        Initialize HTML generator.

        Args:
            config: Configuration dictionary
            template_dir: Directory containing templates (optional)
            model_processor: ModelProcessor instance for downloading images (optional)
        """
        self.config = config
        self.dry_run = config.get("dry_run", False)

        # Initialize components
        self.path_manager = PathManager(config)
        self.renderer = TemplateRenderer(template_dir)
        self.context_builder = ContextBuilder(config, model_processor)

    def generate_html(self, file_path: str, metadata: Dict[str, Any]) -> str:
        """
        Generate HTML for model.

        Args:
            file_path: Path to model file
            metadata: Model metadata

        Returns:
            Path to generated HTML file
        """
        # Get HTML path
        html_path = self.path_manager.get_html_path(file_path)

        # Check if in dry run mode
        if self.dry_run:
            logger.info(f"Dry run: Would generate HTML for {file_path} at {html_path}")
            return html_path

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(html_path), exist_ok=True)

        # Build context
        context = self.context_builder.build_model_context(file_path, metadata)

        # Render template
        html = self.renderer.render_model(context)

        # Write HTML file
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.debug(f"Generated HTML for {file_path} at {html_path}")

        return html_path

    def generate_gallery(
        self,
        file_paths: List[str],
        output_path: str,
        title: str = "Model Gallery",
        include_existing: bool = True,
    ) -> str:
        """
        Generate gallery HTML for multiple models.

        Args:
            file_paths: List of model file paths
            output_path: Path to output HTML file
            title: Gallery title
            include_existing: Whether to include existing model card HTML files

        Returns:
            Path to generated HTML file
        """
        # Check if in dry run mode
        if self.dry_run:
            logger.info(f"Dry run: Would generate gallery at {output_path}")
            return output_path

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Combine newly processed files with existing HTML files if requested
        all_file_paths = list(file_paths)  # Create a copy of the list

        if include_existing:
            # Always scan for existing HTML files, especially now that we might have organized files
            logger.info(
                "Scanning for existing model card HTML files (including in organized directories)"
            )

            # Get path IDs from job configuration if available
            path_ids = self.config.get("gallery_path_ids")  # Use the path_ids from job config

            # Find existing HTML files
            html_files = find_html_files(self.config, path_ids)

            if html_files:
                logger.info(f"Found {len(html_files)} existing model card HTML files")
                # Add HTML files that aren't already in all_file_paths
                for html_path in html_files:
                    if html_path not in all_file_paths:
                        all_file_paths.append(html_path)
            else:
                logger.info("No existing model card HTML files found")

        # Build context with output path for relative path calculation
        context = self.context_builder.build_gallery_context(all_file_paths, title, output_path)

        # Render template
        html = self.renderer.render_gallery(context)

        # Write HTML file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.debug(f"Generated gallery at {output_path}")

        return output_path

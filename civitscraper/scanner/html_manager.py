"""
HTML manager for CivitScraper.

This module handles generating HTML for models.
"""

import logging
import os
from typing import Any, Dict, Optional

from .discovery import get_html_path

logger = logging.getLogger(__name__)


class HTMLManager:
    """
    Manager for HTML generation.

    This class handles generating HTML for models.
    """

    def __init__(self, config: Dict[str, Any], html_generator: Any):
        """
        Initialize HTML manager.

        Args:
            config: Configuration dictionary
            html_generator: HTML generator used for detail pages
        """
        self.config = config
        self.html_generator = html_generator

        # Get output configuration
        self.output_config = config.get("output", {})

        # Get dry run flag
        self.dry_run = config.get("dry_run", False)

    def generate_html(
        self, file_path: str, metadata: Dict[str, Any], force_refresh: bool = False
    ) -> Optional[str]:
        """
        Generate HTML for model.

        Args:
            file_path: Path to model file
            metadata: Model metadata
            force_refresh: Whether to force refresh HTML

        Returns:
            Path to generated HTML file, or None if generation failed
        """
        logger.debug(f"Generating HTML for {file_path}")

        # Get HTML path
        html_path = get_html_path(file_path, self.config)

        # Check if generate_gallery is enabled
        generate_gallery = (
            self.output_config.get("metadata", {}).get("html", {}).get("generate_gallery", False)
        )

        # Check if we should skip existing HTML files using HTML-specific setting
        html_config = self.output_config.get("metadata", {}).get("html", {})
        skip_existing_html = html_config.get("skip_existing_html", True)

        if (
            skip_existing_html
            and os.path.exists(html_path)
            and not force_refresh
            and not generate_gallery
        ):
            logger.info(f"Skipping existing HTML at {html_path}")
            return html_path

        if self.dry_run:
            # Simulate HTML generation in dry run mode
            logger.info(f"Dry run: Would generate HTML at {html_path}")
            return html_path

        try:
            max_count = self.output_config.get("images", {}).get("max_count")
            if max_count is not None:
                logger.debug(f"Using max_count: {max_count} for HTML generation")

            self.html_generator.output_config = self.output_config
            html_path = str(self.html_generator.generate_html(file_path, metadata))
            logger.debug(f"Generated HTML using templates at {html_path}")
            return html_path
        except Exception as e:
            logger.error(f"Error generating HTML for {file_path}: {e}")
            return None

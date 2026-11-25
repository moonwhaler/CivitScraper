"""
Template rendering for HTML generation.

This module handles Jinja template loading and rendering.
"""

import logging
import os
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .filters import FILTERS

logger = logging.getLogger(__name__)


class TemplateRenderer:
    """Renderer for Jinja templates."""

    def __init__(self, template_dir: Optional[str] = None):
        """
        Initialize template renderer.

        Args:
            template_dir: Directory containing templates
        """
        if template_dir is None:
            template_dir = os.path.join(os.path.dirname(__file__), "templates")

        logger.debug(f"Using template directory: {template_dir}")
        self.template_dir: str = template_dir

        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

        # Add a function to read css/js files. Every detail page inlines the same
        # few assets, so each is read once per renderer.
        self._file_cache: Dict[str, Markup] = {}
        self.env.globals["read_file"] = self._read_file
        self.env.filters.update(FILTERS)

        self.model_template = self.env.get_template("model.html")
        self.gallery_template = self.env.get_template("gallery.html")

    def _read_file(self, file_path: str) -> Markup:
        """
        Read a CSS/JS file for inlining into a ``<style>`` or ``<script>`` element.

        The content is our own template asset, so it is marked safe: autoescaping
        would turn quotes and ``>`` into entities, which browsers do not decode
        inside ``<style>``/``<script>``.

        Args:
            file_path: Path to file relative to templates directory

        Returns:
            File content, marked safe for the template
        """
        cached = self._file_cache.get(file_path)
        if cached is not None:
            return cached

        loader = self.env.loader
        if not isinstance(loader, FileSystemLoader):
            raise RuntimeError("Template loader not properly initialized")
        template_dir = loader.searchpath[0]
        full_path = os.path.join(template_dir, file_path)

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = Markup(f.read())
            self._file_cache[file_path] = content
            return content
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return Markup(f"/* Error reading {os.path.basename(file_path)} */")

    def render_model(self, context: Dict[str, Any]) -> str:
        """
        Render model template.

        Args:
            context: Template context

        Returns:
            Rendered HTML
        """
        try:
            html = self.model_template.render(**context)
            logger.debug(f"Rendered model template with {len(context)} context variables")
            return str(html)
        except Exception as e:
            logger.error(f"Error rendering model template: {e}")
            raise

    def render_gallery(self, context: Dict[str, Any]) -> str:
        """
        Render gallery template.

        Args:
            context: Template context

        Returns:
            Rendered HTML
        """
        try:
            html = self.gallery_template.render(**context)
            logger.debug(f"Rendered gallery template with {len(context)} context variables")
            return str(html)
        except Exception as e:
            logger.error(f"Error rendering gallery template: {e}")
            raise

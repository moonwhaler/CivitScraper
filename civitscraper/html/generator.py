"""
HTML generator for CivitScraper.

This module handles generating HTML pages for models using Jinja templates.
"""

import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

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
        html_path = self.path_manager.get_html_path(file_path)

        if self.dry_run:
            logger.info(f"Dry run: Would generate HTML for {file_path} at {html_path}")
            return html_path

        os.makedirs(os.path.dirname(html_path), exist_ok=True)

        context = self.context_builder.build_model_context(file_path, metadata)

        html = self.renderer.render_model(context)

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
        if self.dry_run:
            logger.info(f"Dry run: Would generate gallery at {output_path}")
            return output_path

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Dictionary to store unique models, keyed by model name
        # Value is a tuple of (file_path, is_organized)
        unique_models: Dict[str, Tuple[str, bool]] = {}

        for file_path in file_paths:
            model_name = os.path.splitext(os.path.basename(file_path))[0]
            is_organized = "/organized/" in file_path
            if model_name not in unique_models or (
                is_organized and not unique_models[model_name][1]
            ):
                unique_models[model_name] = (file_path, is_organized)

        if include_existing:
            logger.info(
                "Scanning for existing model card HTML files (including in organized directories)"
            )

            # Get path IDs from job configuration if available
            path_ids = self.config.get("gallery_path_ids")  # Use the path_ids from job config

            html_files = find_html_files(self.config, path_ids)

            if html_files:
                logger.info(f"Found {len(html_files)} existing model card HTML files")
                for html_path in html_files:
                    model_name = os.path.splitext(os.path.basename(html_path))[0]
                    is_organized = "/organized/" in html_path
                    if model_name not in unique_models or (
                        is_organized and not unique_models[model_name][1]
                    ):
                        unique_models[model_name] = (html_path, is_organized)
            else:
                logger.info("No existing model card HTML files found")

        all_file_paths = [path for path, _ in unique_models.values()]
        logger.info(f"Processing {len(all_file_paths)} unique models")

        output_dir = os.path.dirname(output_path)
        css_output_dir = os.path.join(output_dir, "css")
        js_output_dir = os.path.join(output_dir, "js")
        data_output_dir = os.path.join(output_dir, "data")
        os.makedirs(css_output_dir, exist_ok=True)
        os.makedirs(js_output_dir, exist_ok=True)
        os.makedirs(data_output_dir, exist_ok=True)

        template_dir = os.path.dirname(self.renderer.gallery_template.filename)
        css_source_dir = os.path.join(template_dir, "css")
        js_source_dir = os.path.join(template_dir, "js")

        assets_to_copy = {
            "css": ["base.css", "components.css", "gallery.css"],
            "js": ["base.js", "gallery.js"],  # Assuming gallery.js will be created
        }

        logger.debug(f"Copying assets to {output_dir}")
        asset_paths_context = {}
        try:
            for asset_type, filenames in assets_to_copy.items():
                source_dir = css_source_dir if asset_type == "css" else js_source_dir
                dest_dir = css_output_dir if asset_type == "css" else js_output_dir
                for filename in filenames:
                    source_path = os.path.join(source_dir, filename)
                    dest_path = os.path.join(dest_dir, filename)
                    if os.path.exists(source_path):
                        shutil.copy2(source_path, dest_path)
                        relative_path = os.path.join(asset_type, filename)
                        context_key = f"{asset_type}_{filename.split('.')[0]}_path"
                        asset_paths_context[context_key] = relative_path
                        logger.debug(f"Copied {source_path} to {dest_path}")
                    else:
                        logger.warning(f"Asset file not found, skipping copy: {source_path}")
        except Exception as e:
            logger.error(f"Error copying assets: {e}")

        # Build model data list using ContextBuilder (which now returns raw data)
        # Note: build_gallery_context might need adjustment if its internal processing
        # relies heavily on output_path for relative paths *within* the model data itself.
        # For now, assume it returns the necessary data per model.
        models_data = []
        for file_path in all_file_paths:
            model_data = self.context_builder._process_gallery_model(file_path, output_path)
            if model_data:
                models_data.append(model_data)

            data_js_path = os.path.join(data_output_dir, "models_data.js")
            # Default empty
            js_content = "const allModelsData = [];"
        try:
            # Serialize directly to JSON, no special escaping needed for JS file
            json_string = json.dumps(models_data, separators=(",", ":"))
            # Explicitly assign to window object
            js_content = f"window.allModelsData = {json_string}" + ";"
            logger.debug(f"Serialized {len(models_data)} models for JS file.")
        except Exception as e:
            logger.error(f"Error serializing gallery data for JS file: {e}")
            # js_content remains "const allModelsData = [];"

        try:
            with open(data_js_path, "w", encoding="utf-8") as f:
                f.write(js_content)
            logger.debug(f"Wrote models data to {data_js_path}")
        except Exception as e:
            logger.error(f"Error writing models data JS file {data_js_path}: {e}")

        context = {
            "title": title,
            "models_data_js_path": "data/models_data.js",  # Relative path for HTML
            **asset_paths_context,
        }

        html = self.renderer.render_gallery(context)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.debug(f"Generated gallery at {output_path}")

        return output_path

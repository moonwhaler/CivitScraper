"""
HTML generator for CivitScraper.

This module handles generating HTML pages for models using Jinja templates.
"""

import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from ..scanner.discovery import cached_listings, find_html_files
from ..utils.fs import atomic_write
from .context import ContextBuilder
from .gallery_data import (
    collapse_candidates,
    make_cards_portable,
    slim_cards_for_js,
    unmatched_entries,
)
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

    def __init__(self, config: Dict[str, Any], template_dir: Optional[str] = None):
        """
        Initialize HTML generator.

        Args:
            config: Configuration dictionary
            template_dir: Directory containing templates (optional)
        """
        self.config = config
        self.dry_run = config.get("dry_run", False)

        self.path_manager = PathManager(config)
        self.renderer = TemplateRenderer(template_dir)
        self.context_builder = ContextBuilder(config)

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

        atomic_write(html_path, html)

        logger.debug(f"Generated HTML for {file_path} at {html_path}")

        return html_path

    def _gallery_card(
        self, file_path: str, output_path: str, duplicates_of: Dict[str, List[str]]
    ) -> Optional[Dict[str, Any]]:
        """Build one gallery card and attach the duplicate copies found for it."""
        card = self.context_builder._process_gallery_model(file_path, output_path)
        if card is not None:
            card["duplicates"] = duplicates_of.get(file_path, [])
        return card

    def generate_gallery(
        self,
        file_paths: List[str],
        output_path: str,
        title: str = "Model Gallery",
        include_existing: bool = True,
        unmatched: Optional[List[Tuple[str, str]]] = None,
    ) -> str:
        """
        Generate gallery HTML for multiple models.

        Args:
            file_paths: List of model file paths
            output_path: Path to output HTML file
            title: Gallery title
            include_existing: Whether to include existing model card HTML files
            unmatched: (model file, reason) for scanned files without a card, shown
                in the gallery's "Not on CivitAI / no metadata" panel

        Returns:
            Path to generated HTML file
        """
        if self.dry_run:
            logger.info(f"Dry run: Would generate gallery at {output_path}")
            return output_path

        # A bare filename ("gallery.html", as in the README quick start) has an empty
        # dirname, which os.makedirs rejects; resolve against the working directory.
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        candidates: List[str] = list(file_paths)

        if include_existing:
            logger.info(
                "Scanning for existing model card HTML files (including in organized directories)"
            )

            # Get path IDs from job configuration if available
            path_ids = self.config.get("gallery_path_ids")  # Use the path_ids from job config

            html_files = find_html_files(self.config, path_ids)

            if html_files:
                logger.info(f"Found {len(html_files)} existing model card HTML files")
                candidates.extend(html_files)
            else:
                logger.info("No existing model card HTML files found")

        # One path per card; same-version copies at several locations are recorded
        # as duplicates of that card.
        card_sources = collapse_candidates(candidates, self.context_builder)
        duplicates_of = {path: dups for path, dups in card_sources}
        all_file_paths = [path for path, _ in card_sources]
        logger.info(f"Processing {len(all_file_paths)} unique models")

        # Check if there are any models to process before creating directories/assets
        if not all_file_paths:
            logger.info("No models found to generate gallery. Skipping gallery creation.")
            return output_path

        output_dir = os.path.dirname(output_path)
        css_output_dir = os.path.join(output_dir, "css")
        js_output_dir = os.path.join(output_dir, "js")
        data_output_dir = os.path.join(output_dir, "data")
        os.makedirs(css_output_dir, exist_ok=True)
        os.makedirs(js_output_dir, exist_ok=True)
        os.makedirs(data_output_dir, exist_ok=True)

        template_dir = self.renderer.template_dir
        css_source_dir = os.path.join(template_dir, "css")
        js_source_dir = os.path.join(template_dir, "js")

        # Context keys follow the file names: css_theme_path, js_gallery_path, ...
        assets_to_copy = {
            "css": ["theme.css", "gallery.css"],
            "js": ["common.js", "gallery.js"],
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
                        # A URL path for the page, not a filesystem path
                        relative_path = f"{asset_type}/{filename}"
                        context_key = f"{asset_type}_{filename.split('.')[0]}_path"
                        asset_paths_context[context_key] = relative_path
                        logger.debug(f"Copied {source_path} to {dest_path}")
                    else:
                        logger.warning(f"Asset file not found, skipping copy: {source_path}")
        except Exception as e:
            logger.error(f"Error copying assets: {e}")

        # Build model data list using ContextBuilder with parallel processing
        # for better performance with large model collections
        import concurrent.futures

        models_data = []

        # Building cards only reads existing files, so directory listings can be
        # shared across all models (one listing per folder instead of one per model).
        with cached_listings():
            # Use parallel processing for large collections
            if len(all_file_paths) > 10:
                max_workers = min(8, len(all_file_paths))
                logger.debug(f"Processing {len(all_file_paths)} models with {max_workers} workers")

                def process_model(fp: str) -> Optional[Dict[str, Any]]:
                    return self._gallery_card(fp, output_path, duplicates_of)

                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(process_model, fp): fp for fp in all_file_paths}
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            model_data = future.result()
                            if model_data:
                                models_data.append(model_data)
                        except Exception as e:
                            logger.error(f"Error processing model for gallery: {e}")
            else:
                # Sequential processing for small collections
                for file_path in all_file_paths:
                    model_data = self._gallery_card(file_path, output_path, duplicates_of)
                    if model_data:
                        models_data.append(model_data)

        # as_completed order is arbitrary; sort for a deterministic gallery file.
        models_data.sort(key=lambda card: (str(card.get("name")), str(card.get("html_path"))))

        # Merge per-file cards so each CivitAI model is a single gallery card
        # (collapses multiple local versions; attaches local+remote version list).
        models_data = self.context_builder.merge_gallery_models(
            models_data, self.context_builder.domains
        )
        logger.debug(f"Merged into {len(models_data)} unique model cards")

        # Paths relative to the gallery keep links working when the collection is
        # moved or mounted elsewhere together with the gallery.
        html_config = self.config.get("output", {}).get("metadata", {}).get("html", {})
        portable = html_config.get("portable_paths", True)
        make_cards_portable(models_data, output_dir, portable)
        unmatched_data = unmatched_entries(unmatched or [], output_dir, portable)

        data_js_path = os.path.join(data_output_dir, "models_data.js")
        # If the data cannot be serialized, the page shows its "gallery data is
        # missing, run regenerate-html" state rather than an empty gallery.
        js_content = "window.allModelsData = null;"
        try:
            # Serialize directly to JSON, no special escaping needed for JS file
            json_string = json.dumps(slim_cards_for_js(models_data), separators=(",", ":"))
            unmatched_json = json.dumps(unmatched_data, separators=(",", ":"))
            # Explicitly assign to window object
            js_content = (
                f"window.allModelsData = {json_string};\n"
                f"window.galleryUnmatched = {unmatched_json};"
            )
            logger.debug(f"Serialized {len(models_data)} models for JS file.")
        except Exception as e:
            logger.error(f"Error serializing gallery data for JS file: {e}")

        try:
            atomic_write(data_js_path, js_content)
            logger.debug(f"Wrote models data to {data_js_path}")
        except Exception as e:
            logger.error(f"Error writing models data JS file {data_js_path}: {e}")

        context = {
            "title": title,
            "models_data_js_path": "data/models_data.js",  # Relative path for HTML
            **asset_paths_context,
        }

        html = self.renderer.render_gallery(context)

        atomic_write(output_path, html)

        logger.debug(f"Generated gallery at {output_path}")

        return output_path

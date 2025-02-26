"""
HTML generator for CivitScraper.

This module handles generating HTML pages for models using Jinja templates.
"""

import os
import logging
from typing import Dict, Any, List, Optional

from .paths import PathManager
from .renderer import TemplateRenderer
from .context import ContextBuilder
from .images import ImageHandler
from .sanitizer import DataSanitizer

logger = logging.getLogger(__name__)


class HTMLGenerator:
    """
    Generator for HTML pages.
    
    This class orchestrates the HTML generation process using the various
    components for path management, template rendering, context preparation,
    image handling, and data sanitization.
    """
    
    def __init__(self, config: Dict[str, Any], template_dir: Optional[str] = None, model_processor=None):
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
    
    def generate_gallery(self, file_paths: List[str], output_path: str, title: str = "Model Gallery") -> str:
        """
        Generate gallery HTML for multiple models.
        
        Args:
            file_paths: List of model file paths
            output_path: Path to output HTML file
            title: Gallery title
            
        Returns:
            Path to generated HTML file
        """
        # Check if in dry run mode
        if self.dry_run:
            logger.info(f"Dry run: Would generate gallery at {output_path}")
            return output_path
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Build context with output path for relative path calculation
        context = self.context_builder.build_gallery_context(file_paths, title, output_path)
        
        # Render template
        html = self.renderer.render_gallery(context)
        
        # Write HTML file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        
        logger.debug(f"Generated gallery at {output_path}")
        
        return output_path

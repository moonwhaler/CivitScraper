"""
Template rendering for HTML generation.

This module handles Jinja template loading and rendering.
"""

import os
import logging
from typing import Dict, Any
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)


class TemplateRenderer:
    """
    Renderer for Jinja templates.
    """
    
    def __init__(self, template_dir: str = None):
        """
        Initialize template renderer.
        
        Args:
            template_dir: Directory containing templates
        """
        # Get template directory
        if template_dir is None:
            # Use default template directory
            template_dir = os.path.join(os.path.dirname(__file__), "templates")
        
        logger.debug(f"Using template directory: {template_dir}")
        
        # Create Jinja environment
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )
        
        # Load templates
        self.model_template = self.env.get_template("model.html")
        self.gallery_template = self.env.get_template("gallery.html")
    
    def render_model(self, context: Dict[str, Any]) -> str:
        """
        Render model template.
        
        Args:
            context: Template context
            
        Returns:
            Rendered HTML
        """
        try:
            # Render template
            html = self.model_template.render(**context)
            logger.debug(f"Rendered model template with {len(context)} context variables")
            return html
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
            # Render template
            html = self.gallery_template.render(**context)
            logger.debug(f"Rendered gallery template with {len(context)} context variables")
            return html
        except Exception as e:
            logger.error(f"Error rendering gallery template: {e}")
            raise

"""
HTML generator for CivitScraper.

This module handles generating HTML pages for models using Jinja templates.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..scanner.discovery import get_html_path, get_image_path

logger = logging.getLogger(__name__)


class HTMLGenerator:
    """
    Generator for HTML pages.
    """
    
    def __init__(self, config: Dict[str, Any], template_dir: Optional[str] = None):
        """
        Initialize HTML generator.
        
        Args:
            config: Configuration
            template_dir: Directory containing templates
        """
        self.config = config
        
        # Get output configuration
        self.output_config = config.get("output", {})
        
        # Get dry run flag
        self.dry_run = config.get("dry_run", False)
        
        # Get template directory
        if template_dir is None:
            # Use default template directory
            template_dir = os.path.join(os.path.dirname(__file__), "templates")
        
        # Create Jinja environment
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )
        
        # Load templates
        self.model_template = self.env.get_template("model.html")
        self.gallery_template = self.env.get_template("gallery.html")
    
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
        html_path = get_html_path(file_path, self.config)
        
        # Check if in dry run mode
        if self.dry_run:
            logger.info(f"Dry run: Would generate HTML for {file_path} at {html_path}")
            return html_path
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        
        # Prepare context
        context = self._prepare_context(file_path, metadata)
        
        # Render template
        html = self.model_template.render(**context)
        
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
        
        # Prepare context
        context = {
            "title": title,
            "models": [],
        }
        
        # Add models to context
        for file_path in file_paths:
            # Get metadata path
            metadata_path = os.path.splitext(file_path)[0] + ".json"
            
            # Check if metadata exists
            if not os.path.isfile(metadata_path):
                logger.warning(f"Metadata not found for {file_path}")
                continue
            
            # Load metadata
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except Exception as e:
                logger.error(f"Error loading metadata for {file_path}: {e}")
                continue
            
            # Get HTML path
            html_path = get_html_path(file_path, self.config)
            
            # Get preview image path
            preview_image_path = get_image_path(file_path, self.config, "preview0")
            
            # Calculate relative paths
            output_dir = os.path.dirname(output_path)
            html_rel_path = os.path.relpath(html_path, output_dir)
            
            # Log paths for debugging
            logger.debug(f"Gallery output path: {output_path}")
            logger.debug(f"HTML path: {html_path}")
            logger.debug(f"HTML relative path: {html_rel_path}")
            
            preview_rel_path = None
            if os.path.isfile(preview_image_path):
                preview_rel_path = os.path.relpath(preview_image_path, output_dir)
                logger.debug(f"Preview image path: {preview_image_path}")
                logger.debug(f"Preview relative path: {preview_rel_path}")
            
            # Add model to context
            context["models"].append({
                "name": metadata.get("name", "Unknown"),
                "type": metadata.get("model", {}).get("type", "Unknown"),
                "creator": metadata.get("model", {}).get("creator", {}).get("username", "Unknown"),
                "description": metadata.get("description", ""),
                "html_path": html_rel_path,
                "preview_image_path": preview_rel_path,
            })
        
        # Render template
        html = self.gallery_template.render(**context)
        
        # Write HTML file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        
        logger.debug(f"Generated gallery at {output_path}")
        
        return output_path
    
    def _prepare_context(self, file_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare context for template rendering.
        
        Args:
            file_path: Path to model file
            metadata: Model metadata
            
        Returns:
            Template context
        """
        # Get model information
        model_info = metadata.get("model", {})
        
        # Get model name - use the model name from metadata
        model_name = metadata.get("model", {}).get("name", metadata.get("name", "Unknown"))
        
        # Get model type
        model_type = model_info.get("type", "Unknown")
        
        # Get model creator
        creator = model_info.get("creator", {}).get("username", "Unknown")
        
        # Get model description
        description = metadata.get("description", "")
        
        # Get model tags
        tags = model_info.get("tags", [])
        
        # Get model stats
        stats = metadata.get("stats", {})
        
        # Get model images
        images = metadata.get("images", [])
        
        # Get max_count from configuration
        max_count = self.output_config.get("images", {}).get("max_count", 4)
        
        # Log the max_count value for debugging
        logger.debug(f"HTMLGenerator using max_count: {max_count} for file: {file_path}")
        
        # Log the number of images before limiting
        logger.debug(f"HTMLGenerator number of images before limiting: {len(images)}")
        
        # Limit number of images
        images = images[:max_count]
        
        # Log the number of images after limiting
        logger.debug(f"HTMLGenerator number of images after limiting to max_count {max_count}: {len(images)}")
        
        # Get image paths
        image_paths = []
        for i, image in enumerate(images):
            # Get image URL
            image_url = image.get("url")
            if not image_url:
                continue
            
            # Get image extension
            ext = os.path.splitext(image_url)[1]
            
            # Get the image path with the index number
            # The ModelProcessor downloads images with filenames that include the index number
            image_path = get_image_path(file_path, self.config, f"preview{i}", ext)
            
            logger.debug(f"Looking for indexed image file ({i}): {image_path}")
            
            # Check if the indexed image file exists
            if os.path.isfile(image_path):
                # Get image metadata
                image_meta = image.get("meta", {})
                # Ensure image_meta is a dictionary, even if meta is None
                if image_meta is None:
                    image_meta = {}
                
                # Get HTML path
                html_path = get_html_path(file_path, self.config)
                html_dir = os.path.dirname(html_path)
                
                # Calculate relative path from HTML to image
                rel_path = os.path.relpath(image_path, html_dir)
                
                # Log paths for debugging
                logger.debug(f"HTML path: {html_path}")
                logger.debug(f"Found indexed image path: {image_path}")
                logger.debug(f"Relative path: {rel_path}")
                
                # Add image to list
                image_paths.append({
                    "path": rel_path,
                    "prompt": image_meta.get("prompt", ""),
                    "negative_prompt": image_meta.get("negativePrompt", ""),
                    "sampler": image_meta.get("sampler", ""),
                    "cfg_scale": image_meta.get("cfgScale", ""),
                    "steps": image_meta.get("steps", ""),
                    "seed": image_meta.get("seed", ""),
                    "model": image_meta.get("Model", ""),
                })
            else:
                # If the indexed image file doesn't exist, try to download it
                
                # Check if image exists
                if os.path.isfile(image_path):
                    # Get image metadata
                    image_meta = image.get("meta", {})
                    # Ensure image_meta is a dictionary, even if meta is None
                    if image_meta is None:
                        image_meta = {}
                    
                    # Get HTML path
                    html_path = get_html_path(file_path, self.config)
                    html_dir = os.path.dirname(html_path)
                    
                    # Calculate relative path from HTML to image
                    rel_path = os.path.relpath(image_path, html_dir)
                    
                    # Log paths for debugging
                    logger.debug(f"HTML path: {html_path}")
                    logger.debug(f"Image path: {image_path}")
                    logger.debug(f"Relative path: {rel_path}")
                    
                    # Add image to list
                    image_paths.append({
                        "path": rel_path,
                        "prompt": image_meta.get("prompt", ""),
                        "negative_prompt": image_meta.get("negativePrompt", ""),
                        "sampler": image_meta.get("sampler", ""),
                        "cfg_scale": image_meta.get("cfgScale", ""),
                        "steps": image_meta.get("steps", ""),
                        "seed": image_meta.get("seed", ""),
                        "model": image_meta.get("Model", ""),
                    })
                else:
                    # Check if in dry run mode
                    if self.dry_run:
                        logger.info(f"Dry run: Would download image {i+1}/{len(images)} from {image.get('url')} to {image_path}")
                    else:
                        # Try to download the image
                        try:
                            # Create directory if it doesn't exist
                            os.makedirs(os.path.dirname(image_path), exist_ok=True)
                            
                            # Download image
                            logger.debug(f"Downloading image {i+1}/{len(images)} for {file_path}")
                            
                            # Get image URL
                            image_url = image.get("url")
                            if image_url:
                                # Use requests to download the image
                                import requests
                                response = requests.get(image_url, stream=True)
                                if response.status_code == 200:
                                    with open(image_path, 'wb') as f:
                                        for chunk in response.iter_content(1024):
                                            f.write(chunk)
                                    
                                    # Get HTML path
                                    html_path = get_html_path(file_path, self.config)
                                    html_dir = os.path.dirname(html_path)
                                    
                                    # Calculate relative path from HTML to image
                                    rel_path = os.path.relpath(image_path, html_dir)
                                    
                                    # Log paths for debugging
                                    logger.debug(f"HTML path: {html_path}")
                                    logger.debug(f"Image path: {image_path}")
                                    logger.debug(f"Relative path: {rel_path}")
                                    
                                    # Get image metadata
                                    image_meta = image.get("meta", {})
                                    # Ensure image_meta is a dictionary, even if meta is None
                                    if image_meta is None:
                                        image_meta = {}
                                        
                                    # Add image to list
                                    image_paths.append({
                                        "path": rel_path,
                                        "prompt": image_meta.get("prompt", ""),
                                        "negative_prompt": image_meta.get("negativePrompt", ""),
                                        "sampler": image_meta.get("sampler", ""),
                                        "cfg_scale": image_meta.get("cfgScale", ""),
                                        "steps": image_meta.get("steps", ""),
                                        "seed": image_meta.get("seed", ""),
                                        "model": image_meta.get("Model", ""),
                                    })
                        except Exception as e:
                            logger.error(f"Error downloading image: {e}")
        
        # Create context
        context = {
            "title": model_name,
            "model_name": model_name,
            "model_type": model_type,
            "creator": creator,
            "description": description,
            "tags": tags,
            "stats": stats,
            "images": image_paths,
            "metadata": metadata,
        }
        
        return context

"""
HTML generator for CivitScraper.

This module handles generating HTML pages for models using Jinja templates.
"""

import os
import json
import logging
import re
import base64
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..scanner.discovery import get_html_path, get_image_path

logger = logging.getLogger(__name__)


class HTMLGenerator:
    """
    Generator for HTML pages.
    """
    
    def __init__(self, config: Dict[str, Any], template_dir: Optional[str] = None, model_processor=None):
        """
        Initialize HTML generator.
        
        Args:
            config: Configuration
            template_dir: Directory containing templates
            model_processor: ModelProcessor instance for downloading images (optional)
        """
        self.config = config
        self.model_processor = model_processor
        
        # For backward compatibility with the refactored code
        self.image_manager = None
        if model_processor and hasattr(model_processor, 'image_manager'):
            self.image_manager = model_processor.image_manager
        
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
            
            # Check if the preview is a video
            is_video = False
            if preview_rel_path and preview_image_path.lower().endswith('.mp4'):
                is_video = True
                logger.debug(f"Preview is video: {is_video}")
            
            # Add model to context
            context["models"].append({
                "name": metadata.get("name", "Unknown"),
                "type": metadata.get("model", {}).get("type", "Unknown"),
                "creator": metadata.get("model", {}).get("creator", {}).get("username", "Unknown"),
                "description": metadata.get("description", ""),
                "html_path": html_rel_path,
                "preview_image_path": preview_rel_path,
                "is_video": is_video,
            })
        
        # Render template
        html = self.gallery_template.render(**context)
        
        # Write HTML file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        
        logger.debug(f"Generated gallery at {output_path}")
        
        return output_path
    
    def _sanitize_json_data(self, data: List[Dict[str, Any]]) -> str:
        """
        Sanitize and encode image data to avoid JSON parsing issues.
        
        Args:
            data: List of image data dictionaries
            
        Returns:
            Base64 encoded JSON string
        """
        try:
            # First, sanitize any problematic strings in the data
            sanitized_data = []
            for item in data:
                sanitized_item = {}
                for key, value in item.items():
                    if isinstance(value, str):
                        # Fix common escaping issues in strings
                        # Replace double-escaped parentheses with single-escaped
                        value = re.sub(r'\\\\([()])', r'\\\1', value)
                    sanitized_item[key] = value
                sanitized_data.append(sanitized_item)
            
            # Convert to JSON string
            json_str = json.dumps(sanitized_data, ensure_ascii=False)
            
            # Encode as base64 to avoid any escaping issues
            encoded = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
            
            logger.debug(f"Successfully encoded image data (length: {len(json_str)})")
            return encoded
        except Exception as e:
            logger.error(f"Error encoding image data: {e}")
            # Return empty array as fallback
            return base64.b64encode("[]".encode('utf-8')).decode('utf-8')
    
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
        
        # Get max_count from configuration
        max_count = self.output_config.get("images", {}).get("max_count", 4)
        
        # Log the max_count value for debugging
        logger.debug(f"HTMLGenerator using max_count: {max_count} for file: {file_path}")
        
        # Get image paths
        image_paths = []
        
        # If we have an ImageManager, use it to download images
        if self.image_manager:
            # Use the ImageManager to download images
            logger.debug(f"Using ImageManager to download images for {file_path}")
            image_paths = self.image_manager.download_images(file_path, metadata, max_count)
        # For backward compatibility, try using ModelProcessor if available
        elif self.model_processor and hasattr(self.model_processor, 'download_images'):
            # Use the ModelProcessor to download images
            logger.debug(f"Using ModelProcessor to download images for {file_path}")
            image_paths = self.model_processor.download_images(file_path, metadata, max_count)
        else:
            # Fallback to checking for existing images
            logger.debug(f"No ModelProcessor available, checking for existing images for {file_path}")
            
            # Get model images
            images = metadata.get("images", [])
            
            # Log the number of images before limiting
            logger.debug(f"HTMLGenerator number of images before limiting: {len(images)}")
            
            # Limit number of images
            images = images[:max_count]
            
            # Log the number of images after limiting
            logger.debug(f"HTMLGenerator number of images after limiting to max_count {max_count}: {len(images)}")
            
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
                    
                    # Determine if this is a video file based on extension
                    is_video = image_path.lower().endswith('.mp4')
                    logger.debug(f"File is video: {is_video}")
                    
                    # Add image/video to list
                    image_paths.append({
                        "path": rel_path,
                        "prompt": image_meta.get("prompt", ""),
                        "negative_prompt": image_meta.get("negativePrompt", ""),
                        "sampler": image_meta.get("sampler", ""),
                        "cfg_scale": image_meta.get("cfgScale", ""),
                        "steps": image_meta.get("steps", ""),
                        "seed": image_meta.get("seed", ""),
                        "model": image_meta.get("Model", ""),
                        "is_video": is_video,
                    })
                else:
                    # If the indexed image file doesn't exist, check if a version with a different extension exists
                    # This handles the case where a video file was renamed from .jpeg to .mp4 by the ModelProcessor
                    
                    # Get the base path without extension
                    base_path = os.path.splitext(image_path)[0]
                    
                    # Check for common video extensions
                    video_path = f"{base_path}.mp4"
                    if os.path.isfile(video_path):
                        # Found a video file with the same base name
                        logger.debug(f"Found video file instead of image: {video_path}")
                        
                        # Get image metadata
                        image_meta = image.get("meta", {})
                        # Ensure image_meta is a dictionary, even if meta is None
                        if image_meta is None:
                            image_meta = {}
                        
                        # Get HTML path
                        html_path = get_html_path(file_path, self.config)
                        html_dir = os.path.dirname(html_path)
                        
                        # Calculate relative path from HTML to video
                        rel_path = os.path.relpath(video_path, html_dir)
                        
                        # Log paths for debugging
                        logger.debug(f"HTML path: {html_path}")
                        logger.debug(f"Video path: {video_path}")
                        logger.debug(f"Relative path: {rel_path}")
                        
                        # Add video to list
                        image_paths.append({
                            "path": rel_path,
                            "prompt": image_meta.get("prompt", ""),
                            "negative_prompt": image_meta.get("negativePrompt", ""),
                            "sampler": image_meta.get("sampler", ""),
                            "cfg_scale": image_meta.get("cfgScale", ""),
                            "steps": image_meta.get("steps", ""),
                            "seed": image_meta.get("seed", ""),
                            "model": image_meta.get("Model", ""),
                            "is_video": True,
                        })
                    # If no video file exists, check if the original image exists
                    elif os.path.isfile(image_path):
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
                        
                        # Determine if this is a video file based on extension
                        is_video = image_path.lower().endswith('.mp4')
                        
                        # Add image/video to list
                        image_paths.append({
                            "path": rel_path,
                            "prompt": image_meta.get("prompt", ""),
                            "negative_prompt": image_meta.get("negativePrompt", ""),
                            "sampler": image_meta.get("sampler", ""),
                            "cfg_scale": image_meta.get("cfgScale", ""),
                            "steps": image_meta.get("steps", ""),
                            "seed": image_meta.get("seed", ""),
                            "model": image_meta.get("Model", ""),
                            "is_video": is_video,
                        })
                    # If no image or video file exists, log a warning
                    else:
                        logger.warning(f"Image file not found: {image_path}")
                        # In dry run mode, we would normally download the image
                        if self.dry_run:
                            logger.info(f"Dry run: Would download image {i+1}/{len(images)} from {image.get('url')} to {image_path}")
        
        # Sanitize and encode image data to avoid JSON parsing issues
        encoded_images = self._sanitize_json_data(image_paths)
        
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
            "images_encoded": encoded_images,
            "metadata": metadata,
        }
        
        return context

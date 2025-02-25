"""
File organizer for CivitScraper.

This module handles organizing model files based on metadata.
"""

import os
import json
import shutil
import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class FileOrganizer:
    """
    Organizer for model files.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize file organizer.
        
        Args:
            config: Configuration
        """
        self.config = config
        
        # Get organization configuration
        self.organization_config = config.get("organization", {})
        
        # Get predefined templates
        self.templates = {
            "by_type": "{type}",
            "by_creator": "{creator}",
            "by_type_and_creator": "{type}/{creator}",
            "by_base_model": "{base_model}/{type}",
            "by_nsfw": "{nsfw}/{type}",
            "by_date": "{year}/{month}/{type}",
            "by_model_info": "{model_type}/{model_name}",
        }
    
    def organize_file(self, file_path: str, metadata: Dict[str, Any]) -> Optional[str]:
        """
        Organize a model file.
        
        Args:
            file_path: Path to model file
            metadata: Model metadata
            
        Returns:
            Path to organized file or None if organization failed
        """
        # Check if organization is enabled
        if not self.organization_config.get("enabled", False):
            logger.debug("Organization is disabled")
            return None
        
        try:
            # Get organization template
            template_name = self.organization_config.get("template")
            custom_template = self.organization_config.get("custom_template")
            
            # Get template
            if custom_template:
                template = custom_template
            elif template_name in self.templates:
                template = self.templates[template_name]
            else:
                logger.error(f"Unknown template: {template_name}")
                return None
            
            # Get output directory
            output_dir = self.organization_config.get("output_dir")
            if not output_dir:
                logger.error("No output directory specified")
                return None
            
            # Replace {model_dir} with model directory
            output_dir = output_dir.replace("{model_dir}", os.path.dirname(file_path))
            
            # Get operation mode
            move_files = self.organization_config.get("move_files", False)
            create_symlinks = self.organization_config.get("create_symlinks", False)
            
            # Get dry run flag
            dry_run = self.organization_config.get("dry_run", True)
            
            # Format path using metadata
            relative_path = self._format_path(template, metadata)
            
            # Create target path
            target_dir = os.path.join(output_dir, relative_path)
            target_path = os.path.join(target_dir, os.path.basename(file_path))
            
            # Check if target path exists
            if os.path.exists(target_path):
                logger.warning(f"Target path already exists: {target_path}")
                
                # Handle collision
                target_path = self._handle_collision(target_path)
            
            # Create directory if it doesn't exist
            if not dry_run:
                os.makedirs(target_dir, exist_ok=True)
            
            # Perform file operation
            if dry_run:
                logger.info(f"Dry run: Would {'move' if move_files else 'symlink' if create_symlinks else 'copy'} {file_path} to {target_path}")
            else:
                if move_files:
                    logger.info(f"Moving {file_path} to {target_path}")
                    shutil.move(file_path, target_path)
                elif create_symlinks:
                    logger.info(f"Creating symlink from {file_path} to {target_path}")
                    os.symlink(os.path.abspath(file_path), target_path)
                else:
                    logger.info(f"Copying {file_path} to {target_path}")
                    shutil.copy2(file_path, target_path)
            
            # Organize metadata file
            metadata_path = os.path.splitext(file_path)[0] + ".json"
            if os.path.isfile(metadata_path):
                metadata_target_path = os.path.splitext(target_path)[0] + ".json"
                
                if dry_run:
                    logger.info(f"Dry run: Would {'move' if move_files else 'symlink' if create_symlinks else 'copy'} {metadata_path} to {metadata_target_path}")
                else:
                    if move_files:
                        logger.info(f"Moving {metadata_path} to {metadata_target_path}")
                        shutil.move(metadata_path, metadata_target_path)
                    elif create_symlinks:
                        logger.info(f"Creating symlink from {metadata_path} to {metadata_target_path}")
                        os.symlink(os.path.abspath(metadata_path), metadata_target_path)
                    else:
                        logger.info(f"Copying {metadata_path} to {metadata_target_path}")
                        shutil.copy2(metadata_path, metadata_target_path)
            
            # Organize HTML file
            html_path = os.path.splitext(file_path)[0] + ".html"
            if os.path.isfile(html_path):
                html_target_path = os.path.splitext(target_path)[0] + ".html"
                
                if dry_run:
                    logger.info(f"Dry run: Would {'move' if move_files else 'symlink' if create_symlinks else 'copy'} {html_path} to {html_target_path}")
                else:
                    if move_files:
                        logger.info(f"Moving {html_path} to {html_target_path}")
                        shutil.move(html_path, html_target_path)
                    elif create_symlinks:
                        logger.info(f"Creating symlink from {html_path} to {html_target_path}")
                        os.symlink(os.path.abspath(html_path), html_target_path)
                    else:
                        logger.info(f"Copying {html_path} to {html_target_path}")
                        shutil.copy2(html_path, html_target_path)
            
            # Organize preview images
            preview_path = os.path.splitext(file_path)[0] + ".preview.jpg"
            if os.path.isfile(preview_path):
                preview_target_path = os.path.splitext(target_path)[0] + ".preview.jpg"
                
                if dry_run:
                    logger.info(f"Dry run: Would {'move' if move_files else 'symlink' if create_symlinks else 'copy'} {preview_path} to {preview_target_path}")
                else:
                    if move_files:
                        logger.info(f"Moving {preview_path} to {preview_target_path}")
                        shutil.move(preview_path, preview_target_path)
                    elif create_symlinks:
                        logger.info(f"Creating symlink from {preview_path} to {preview_target_path}")
                        os.symlink(os.path.abspath(preview_path), preview_target_path)
                    else:
                        logger.info(f"Copying {preview_path} to {preview_target_path}")
                        shutil.copy2(preview_path, preview_target_path)
            
            return target_path
        
        except Exception as e:
            logger.error(f"Error organizing {file_path}: {e}")
            return None
    
    def organize_files(self, file_paths: List[str], metadata_dict: Dict[str, Dict[str, Any]]) -> List[Tuple[str, Optional[str]]]:
        """
        Organize multiple model files.
        
        Args:
            file_paths: List of file paths
            metadata_dict: Dictionary of file path -> metadata
            
        Returns:
            List of (file_path, target_path) tuples
        """
        # Check if organization is enabled
        if not self.organization_config.get("enabled", False):
            logger.debug("Organization is disabled")
            return [(file_path, None) for file_path in file_paths]
        
        # Organize files
        results = []
        
        for file_path in file_paths:
            # Get metadata
            metadata = metadata_dict.get(file_path)
            if not metadata:
                logger.warning(f"No metadata found for {file_path}")
                results.append((file_path, None))
                continue
            
            # Organize file
            target_path = self.organize_file(file_path, metadata)
            
            # Add to results
            results.append((file_path, target_path))
        
        return results
    
    def _format_path(self, template: str, metadata: Dict[str, Any]) -> str:
        """
        Format path using metadata.
        
        Args:
            template: Path template
            metadata: Model metadata
            
        Returns:
            Formatted path
        """
        # Get model information
        model_info = metadata.get("model", {})
        
        # Get model name
        model_name = metadata.get("name", "Unknown")
        
        # Get model type
        model_type = model_info.get("type", "Unknown")
        
        # Get model creator
        creator = model_info.get("creator", {}).get("username", "Unknown")
        
        # Get base model
        base_model = metadata.get("baseModel", "Unknown")
        
        # Get NSFW status
        nsfw = "nsfw" if model_info.get("nsfw", False) else "sfw"
        
        # Get creation date
        created_at = metadata.get("createdAt", "")
        year = created_at[:4] if created_at else "Unknown"
        month = created_at[5:7] if created_at else "Unknown"
        
        # Format path
        path = template
        path = path.replace("{model_name}", self._sanitize_path(model_name))
        path = path.replace("{model_type}", self._sanitize_path(model_type))
        path = path.replace("{type}", self._sanitize_path(model_type))
        path = path.replace("{creator}", self._sanitize_path(creator))
        path = path.replace("{base_model}", self._sanitize_path(base_model))
        path = path.replace("{nsfw}", nsfw)
        path = path.replace("{year}", year)
        path = path.replace("{month}", month)
        
        return path
    
    def _sanitize_path(self, path: str) -> str:
        """
        Sanitize path.
        
        Args:
            path: Path to sanitize
            
        Returns:
            Sanitized path
        """
        # Replace invalid characters
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in invalid_chars:
            path = path.replace(char, '_')
        
        # Remove leading and trailing dots and spaces
        path = path.strip('. ')
        
        return path
    
    def _handle_collision(self, path: str) -> str:
        """
        Handle path collision.
        
        Args:
            path: Path that already exists
            
        Returns:
            New path
        """
        # Get path components
        dir_path, filename = os.path.split(path)
        name, ext = os.path.splitext(filename)
        
        # Try adding numbers until we find a path that doesn't exist
        counter = 1
        while os.path.exists(path):
            path = os.path.join(dir_path, f"{name}_{counter}{ext}")
            counter += 1
        
        return path

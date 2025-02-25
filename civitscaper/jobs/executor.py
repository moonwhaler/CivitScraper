"""
Job executor for CivitScraper.

This module handles executing jobs defined in the configuration.
"""

import os
import logging
from typing import Dict, Any, List, Optional, Tuple, Set, Callable

from ..api.client import CivitAIClient
from ..scanner.discovery import find_model_files, filter_files
from ..scanner.processor import ModelProcessor
from ..html.generator import HTMLGenerator
from ..organization.organizer import FileOrganizer

logger = logging.getLogger(__name__)


class JobExecutor:
    """
    Executor for jobs.
    """
    
    def __init__(self, config: Dict[str, Any], api_client: CivitAIClient):
        """
        Initialize job executor.
        
        Args:
            config: Configuration
            api_client: CivitAI API client
        """
        self.config = config
        self.api_client = api_client
        
        # Create HTML generator
        self.html_generator = HTMLGenerator(config)
        
        # Create model processor and pass the HTML generator
        self.model_processor = ModelProcessor(config, api_client, self.html_generator)
        
        # Create file organizer
        self.file_organizer = FileOrganizer(config)
    
    def execute_job(self, job_name: str) -> bool:
        """
        Execute a job.
        
        Args:
            job_name: Job name
            
        Returns:
            True if job was executed successfully, False otherwise
        """
        # Get job configuration
        job_config = self.config.get("jobs", {}).get(job_name)
        if not job_config:
            logger.error(f"Job not found: {job_name}")
            return False
        
        # Get job type
        job_type = job_config.get("type")
        if not job_type:
            logger.error(f"No job type specified for job: {job_name}")
            return False
        
        # Execute job based on type
        if job_type == "scan-paths":
            return self._execute_scan_paths_job(job_name, job_config)
        elif job_type == "sync-lora-triggers":
            return self._execute_sync_lora_triggers_job(job_name, job_config)
        else:
            logger.error(f"Unknown job type: {job_type}")
            return False
    
    def execute_all_jobs(self) -> Dict[str, bool]:
        """
        Execute all jobs.
        
        Returns:
            Dictionary of job name -> success
        """
        # Get jobs
        jobs = self.config.get("jobs", {})
        
        # Execute jobs
        results = {}
        
        for job_name in jobs:
            logger.info(f"Executing job: {job_name}")
            success = self.execute_job(job_name)
            results[job_name] = success
            
            if success:
                logger.info(f"Job {job_name} executed successfully")
            else:
                logger.error(f"Job {job_name} failed")
        
        return results
    
    def _execute_scan_paths_job(self, job_name: str, job_config: Dict[str, Any]) -> bool:
        """
        Execute a scan-paths job.
        
        Args:
            job_name: Job name
            job_config: Job configuration
            
        Returns:
            True if job was executed successfully, False otherwise
        """
        try:
            # Get paths
            path_ids = job_config.get("paths", [])
            if not path_ids:
                # If no paths specified, use all LORA paths
                path_ids = [path_id for path_id, path_config in self.config.get("input_paths", {}).items() 
                           if path_config.get("type") == "LORA"]
                if not path_ids:
                    logger.error(f"No paths specified for job: {job_name} and no LORA paths found in configuration")
                    return False
                logger.info(f"No paths specified, using all LORA paths: {path_ids}")
            
            # Get scan options
            recursive = job_config.get("recursive", True)
            skip_existing = job_config.get("skip_existing", True)
            verify_hashes = job_config.get("verify_hashes", True)
            organize = job_config.get("organize", False)
            
            # Find model files
            logger.info(f"Finding model files for paths: {path_ids}")
            path_files = find_model_files(self.config, path_ids)
            
            # Flatten files
            files = []
            for path_id, path_files in path_files.items():
                files.extend(path_files)
            
            # Filter files
            logger.info(f"Found {len(files)} files, filtering...")
            filtered_files = filter_files(files, skip_existing)
            logger.info(f"Filtered to {len(filtered_files)} files")
            
            # Process files
            logger.info(f"Processing {len(filtered_files)} files")
            results = self.model_processor.process_files_in_batches(
                filtered_files,
                verify_hash=verify_hashes,
                force_refresh=False,
            )
            
            # Create metadata dictionary
            metadata_dict = {}
            for file_path, metadata in results:
                if metadata:
                    metadata_dict[file_path] = metadata
            
            # Organize files
            if organize:
                logger.info(f"Organizing {len(metadata_dict)} files")
                self.file_organizer.organize_files(list(metadata_dict.keys()), metadata_dict)
            
            # Generate gallery
            if job_config.get("generate_gallery", False):
                gallery_path = job_config.get("gallery_path", "gallery.html")
                gallery_title = job_config.get("gallery_title", "Model Gallery")
                
                logger.info(f"Generating gallery at {gallery_path}")
                self.html_generator.generate_gallery(list(metadata_dict.keys()), gallery_path, gallery_title)
            
            return True
        
        except Exception as e:
            logger.error(f"Error executing scan-paths job {job_name}: {e}")
            return False
    
    def _execute_sync_lora_triggers_job(self, job_name: str, job_config: Dict[str, Any]) -> bool:
        """
        Execute a sync-lora-triggers job.
        
        Args:
            job_name: Job name
            job_config: Job configuration
            
        Returns:
            True if job was executed successfully, False otherwise
        """
        try:
            # Get paths
            path_ids = job_config.get("paths", [])
            if not path_ids:
                logger.error(f"No paths specified for job: {job_name}")
                return False
            
            # Get loras.json path
            loras_file = job_config.get("loras_file", "loras.json")
            if not loras_file:
                logger.error(f"No loras_file specified for job: {job_name}")
                return False
            
            # Get scan options
            recursive = job_config.get("recursive", True)
            
            # Find model files
            logger.info(f"Finding model files for paths: {path_ids}")
            path_files = find_model_files(self.config, path_ids)
            
            # Flatten files
            files = []
            for path_id, path_files in path_files.items():
                files.extend(path_files)
            
            # Filter to LORA files
            lora_files = []
            for file_path in files:
                # Get metadata path
                metadata_path = os.path.splitext(file_path)[0] + ".json"
                
                # Check if metadata exists
                if not os.path.isfile(metadata_path):
                    continue
                
                # Add to LORA files
                lora_files.append(file_path)
            
            # Check if loras.json exists
            if not os.path.isfile(loras_file):
                logger.error(f"loras.json not found at {loras_file}")
                return False
            
            # Load loras.json
            import json
            with open(loras_file, "r") as f:
                loras_data = json.load(f)
            
            # Update loras.json
            updated_count = 0
            for file_path in lora_files:
                # Get metadata path
                metadata_path = os.path.splitext(file_path)[0] + ".json"
                
                # Load metadata
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                
                # Get activation text
                activation_text = metadata.get("activation text")
                if not activation_text:
                    continue
                
                # Get relative path
                relative_path = os.path.relpath(file_path)
                
                # Find entry in loras.json
                for entry in loras_data:
                    if entry.get("id") == relative_path:
                        # Update entry
                        if "metadata" not in entry:
                            entry["metadata"] = {}
                        
                        entry["metadata"]["lora_triggers"] = activation_text
                        updated_count += 1
                        break
            
            # Save loras.json
            with open(loras_file, "w") as f:
                json.dump(loras_data, f, indent=2)
            
            logger.info(f"Updated {updated_count} entries in loras.json")
            
            return True
        
        except Exception as e:
            logger.error(f"Error executing sync-lora-triggers job {job_name}: {e}")
            return False

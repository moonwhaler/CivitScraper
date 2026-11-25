"""
sync-lora-triggers job for CivitScraper.

Copies each LoRA's trigger words from its sidecar into Krita AI Diffusion's
``loras.json`` (``metadata.lora_triggers`` of the entry with the same filename).
"""

import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from ..config.loader import merge_configs
from ..scanner.discovery import find_metadata_file, find_model_files
from ..utils.fs import atomic_write

logger = logging.getLogger(__name__)

UPDATED = "updated"
SKIPPED = "skipped"
NO_ENTRY = "no_entry"


def trigger_words_of(metadata: Dict[str, Any]) -> Any:
    """
    Return a sidecar's trigger words (``trainedWords``, else ``activation text``).

    Args:
        metadata: Sidecar metadata

    Returns:
        A list or string of trigger words, or a falsy value if there are none
    """
    trigger_words = metadata.get("trainedWords")
    if trigger_words:
        return trigger_words
    return metadata.get("activation text")


def trigger_string(trigger_words: Any) -> str:
    """
    Join trigger words into the comma-separated string Krita stores.

    Args:
        trigger_words: List of words/phrases, or a single string

    Returns:
        Trigger string without stray trailing commas
    """
    if isinstance(trigger_words, list):
        joined = ", ".join(str(word).strip().rstrip(",") for word in trigger_words if word)
        return joined.strip().rstrip(",")
    return str(trigger_words).strip()


def update_entry(
    loras_data: List[Dict[str, Any]], filename: str, trigger_words: Any, overwrite: bool
) -> str:
    """
    Set the triggers of the ``loras.json`` entry whose id ends in ``filename``.

    Args:
        loras_data: Parsed ``loras.json`` (modified in place)
        filename: Model file name to match against each entry's id
        trigger_words: Trigger words to store
        overwrite: Replace triggers an entry already has

    Returns:
        UPDATED, SKIPPED (entry already has triggers and overwrite is off) or
        NO_ENTRY
    """
    for entry in loras_data:
        if os.path.basename(entry.get("id", "")) != filename:
            continue
        logger.debug(f"Found entry with id: {entry.get('id')}")

        if not overwrite:
            current_triggers = entry.get("metadata", {}).get("lora_triggers")
            if current_triggers:
                logger.debug(
                    f"Skipping update for {filename} as it already has triggers: "
                    f"{current_triggers}"
                )
                return SKIPPED

        logger.debug(f"Updating with new triggers: {trigger_words}")
        entry.setdefault("metadata", {})["lora_triggers"] = trigger_string(trigger_words)
        return UPDATED
    return NO_ENTRY


class LoraTriggerSync:
    """One run of a sync-lora-triggers job."""

    def __init__(self, config: Dict[str, Any], job_name: str, job_config: Dict[str, Any]):
        """
        Prepare a sync-lora-triggers job.

        Args:
            config: Global configuration
            job_name: Job name (for log messages)
            job_config: The job's own configuration section
        """
        self.config = config
        self.job_name = job_name
        self.job_config = job_config

    def run(self) -> bool:
        """
        Run the job.

        Returns:
            True if the job was executed successfully, False otherwise
        """
        try:
            return self._run()
        except Exception as e:
            logger.error(f"Error executing sync-lora-triggers job {self.job_name}: {e}")
            logger.debug("Traceback:", exc_info=True)
            return False

    def _lora_files(self, path_ids: List[str]) -> List[Tuple[str, str]]:
        """Return (model file, metadata file) for every scanned model with a sidecar."""
        logger.info(f"Finding model files for paths: {path_ids}")
        path_files = find_model_files(self.config, path_ids, self.job_config.get("recursive"))
        files: List[str] = []
        for path_files_list in path_files.values():
            files.extend(path_files_list)

        # Locate metadata with the same rules as scan jobs (output.base_dir,
        # output.metadata.path/filename from the global config or this job),
        # falling back to the legacy <model>.json next to the model file.
        job_specific_config = merge_configs(self.config, self.job_config)
        lora_files: List[Tuple[str, str]] = []
        for file_path in files:
            metadata_path: Optional[str] = find_metadata_file(file_path, job_specific_config)
            if metadata_path:
                lora_files.append((file_path, metadata_path))
        return lora_files

    def _run(self) -> bool:
        job_config = self.job_config

        path_ids = job_config.get("paths", [])
        if not path_ids:
            logger.error(f"No paths specified for job: {self.job_name}")
            return False

        loras_file = job_config.get("loras_file", "loras.json")
        if not loras_file:
            logger.error(f"No loras_file specified for job: {self.job_name}")
            return False

        overwrite_triggers = job_config.get("overwrite_triggers", True)
        logger.info(f"Overwrite existing triggers: {overwrite_triggers}")

        lora_files = self._lora_files(path_ids)

        if not os.path.isfile(loras_file):
            logger.error(f"loras.json not found at {loras_file}")
            return False

        with open(loras_file, "r") as f:
            loras_data = json.load(f)

        counts = {UPDATED: 0, SKIPPED: 0, NO_ENTRY: 0}
        processed_count = 0
        logger.debug(f"Total files to process: {len(lora_files)}")

        for file_path, metadata_path in lora_files:
            processed_count += 1
            logger.debug(f"Processing {file_path}")

            with open(metadata_path, "r") as f:
                metadata = json.load(f)

            trigger_words = trigger_words_of(metadata)
            if not trigger_words:
                logger.debug(f"No trigger words in trainedWords or activation text for {file_path}")
                continue

            filename = os.path.basename(file_path)
            logger.debug(f"Looking for entry with filename: {filename}")
            outcome = update_entry(loras_data, filename, trigger_words, overwrite_triggers)
            counts[outcome] += 1
            if outcome == NO_ENTRY:
                logger.debug(f"No matching entry found in loras.json for {filename}")

        updated_count = counts[UPDATED]

        # Save loras.json (Krita's own file): never in dry run, keep one backup of
        # the previous version, and write atomically so a crash can't truncate it.
        if self.config.get("dry_run", False) or job_config.get("dry_run", False):
            logger.info(f"Dry run: Would update {updated_count} entries in {loras_file}")
        elif updated_count:
            shutil.copy2(loras_file, loras_file + ".bak")
            atomic_write(loras_file, json.dumps(loras_data, indent=2))
        else:
            logger.info(f"No trigger changes; {loras_file} left untouched")

        logger.info(f"Files processed: {processed_count}")
        logger.info(f"Updated {updated_count} entries in loras.json")
        if not overwrite_triggers:
            logger.info(f"Skipped {counts[SKIPPED]} entries with existing triggers")

        return True

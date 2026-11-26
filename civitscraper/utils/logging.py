"""
Logging utilities for CivitScraper.

This module configures the logging system for the application.
"""

import logging
import logging.handlers
import os
from datetime import datetime
from typing import Any, Dict

LOG_PREFIX = "civitscraper_"
DEFAULT_KEEP_FILES = 10


def prune_logs(log_dir: str, keep: int, current: str = "") -> int:
    """
    Delete the log files of all but the newest ``keep`` runs.

    Every run writes its own ``civitscraper_<timestamp>.log`` (plus ``.log.1``... once
    it rotates), so old runs pile up. ``keep`` <= 0 keeps everything.

    Returns:
        Number of files deleted
    """
    if keep <= 0:
        return 0
    try:
        names = os.listdir(log_dir)
    except OSError:
        return 0
    runs = sorted(
        {n.split(".log", 1)[0] for n in names if n.startswith(LOG_PREFIX) and ".log" in n},
        reverse=True,
    )
    current_run = os.path.basename(current).split(".log", 1)[0]
    stale = {r for r in runs[keep:] if r != current_run}
    deleted = 0
    for name in names:
        if name.startswith(LOG_PREFIX) and name.split(".log", 1)[0] in stale:
            try:
                os.remove(os.path.join(log_dir, name))
                deleted += 1
            except OSError:
                pass
    return deleted


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """
    Set up logging based on configuration.

    Args:
        config: Logging configuration

    Returns:
        Root logger
    """
    logging_config = config.get("logging", {})
    log_level_str = logging_config.get("level", "INFO")
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(log_level)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    if logging_config.get("console", {}).get("enabled", True):
        console_level_str = logging_config.get("console", {}).get("level", log_level_str)
        console_level = getattr(logging, console_level_str.upper(), log_level)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)

        if logging_config.get("console", {}).get("simple", False):
            formatter = logging.Formatter("%(message)s")
        else:
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if logging_config.get("file", {}).get("enabled", False):
        file_level_str = logging_config.get("file", {}).get("level", log_level_str)
        file_level = getattr(logging, file_level_str.upper(), log_level)
        log_dir = logging_config.get("file", {}).get("directory", "logs")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"{LOG_PREFIX}{timestamp}.log")
        max_size = logging_config.get("file", {}).get("max_size", 10) * 1024 * 1024  # MB to bytes
        backup_count = logging_config.get("file", {}).get("backup_count", 5)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_size,
            backupCount=backup_count,
        )
        file_handler.setLevel(file_level)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        keep = logging_config.get("file", {}).get("keep_files", DEFAULT_KEEP_FILES)
        prune_logs(log_dir, int(keep), log_file)

    return logger

"""
Logging utilities for CivitScraper.

This module configures the logging system for the application.
"""

import logging
import logging.handlers
import os
from datetime import datetime
from typing import Any, Dict


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """
    Set up logging based on configuration.

    Args:
        config: Logging configuration

    Returns:
        Root logger
    """
    # Get logging configuration
    logging_config = config.get("logging", {})

    # Get log level
    log_level_str = logging_config.get("level", "INFO")
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # Create root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Configure console logging
    if logging_config.get("console", {}).get("enabled", True):
        console_level_str = logging_config.get("console", {}).get("level", log_level_str)
        console_level = getattr(logging, console_level_str.upper(), log_level)

        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)

        # Create formatter
        if logging_config.get("console", {}).get("simple", False):
            formatter = logging.Formatter("%(message)s")
        else:
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

        console_handler.setFormatter(formatter)

        # Add handler to logger
        logger.addHandler(console_handler)

    # Configure file logging
    if logging_config.get("file", {}).get("enabled", False):
        file_level_str = logging_config.get("file", {}).get("level", log_level_str)
        file_level = getattr(logging, file_level_str.upper(), log_level)

        # Get log directory
        log_dir = logging_config.get("file", {}).get("directory", "logs")

        # Create log directory if it doesn't exist
        os.makedirs(log_dir, exist_ok=True)

        # Get log file name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"civitscraper_{timestamp}.log")

        # Get max size and backup count
        max_size = logging_config.get("file", {}).get("max_size", 10) * 1024 * 1024  # MB to bytes
        backup_count = logging_config.get("file", {}).get("backup_count", 5)

        # Create file handler
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_size,
            backupCount=backup_count,
        )
        file_handler.setLevel(file_level)

        # Create formatter
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)

        # Add handler to logger
        logger.addHandler(file_handler)

    return logger


class ProgressLogger:
    """Logger for tracking progress of operations."""

    def __init__(
        self,
        logger: logging.Logger,
        total: int,
        description: str = "Processing",
        log_interval: int = 10,
    ):
        """
        Initialize progress logger.

        Args:
            logger: Logger to use
            total: Total number of items
            description: Description of operation
            log_interval: Interval for logging progress (in percentage)
        """
        self.logger = logger
        self.total = total
        self.description = description
        self.log_interval = log_interval
        self.current = 0
        self.last_logged_percentage = 0

    def update(self, increment: int = 1):
        """
        Update progress.

        Args:
            increment: Number of items to increment by
        """
        self.current += increment

        # Calculate percentage
        percentage = int(self.current / self.total * 100) if self.total > 0 else 100

        # Log progress at intervals
        if percentage >= self.last_logged_percentage + self.log_interval or percentage == 100:
            self.logger.info(f"{self.description}: {percentage}% ({self.current}/{self.total})")
            self.last_logged_percentage = percentage

    def set_total(self, total: int):
        """
        Set total number of items.

        Args:
            total: Total number of items
        """
        self.total = total

    def set_description(self, description: str):
        """
        Set description of operation.

        Args:
            description: Description of operation
        """
        self.description = description


class BatchProgressTracker:
    """Tracker for batch processing progress."""

    def __init__(
        self,
        logger: logging.Logger,
        total_batches: int,
        total_items: int,
        description: str = "Processing",
    ):
        """
        Initialize batch progress tracker.

        Args:
            logger: Logger to use
            total_batches: Total number of batches
            total_items: Total number of items
            description: Description of operation
        """
        self.logger = logger
        self.total_batches = total_batches
        self.total_items = total_items
        self.description = description
        self.current_batch = 0
        self.current_item = 0
        self.success_count = 0
        self.failure_count = 0
        self.start_time = datetime.now()

    def start_batch(self, batch_number: int, batch_size: int):
        """
        Start a new batch.

        Args:
            batch_number: Batch number
            batch_size: Batch size
        """
        self.current_batch = batch_number
        self.logger.info(
            f"{self.description} - Batch {batch_number}/{self.total_batches} ({batch_size} items)"
        )

    def update(self, success: bool = True):
        """
        Update progress.

        Args:
            success: Whether the operation was successful
        """
        self.current_item += 1

        if success:
            self.success_count += 1
        else:
            self.failure_count += 1

    def end_batch(self):
        """End current batch."""
        batch_percentage = (
            int(self.current_batch / self.total_batches * 100) if self.total_batches > 0 else 100
        )
        item_percentage = (
            int(self.current_item / self.total_items * 100) if self.total_items > 0 else 100
        )

        self.logger.info(
            f"{self.description} - Batch {self.current_batch}/{self.total_batches} complete "
            f"({batch_percentage}% of batches, {item_percentage}% of items)"
        )

    def end(self):
        """End tracking."""
        elapsed = datetime.now() - self.start_time
        elapsed_seconds = elapsed.total_seconds()

        items_per_second = self.current_item / elapsed_seconds if elapsed_seconds > 0 else 0

        self.logger.info(
            f"{self.description} complete - "
            f"{self.current_item}/{self.total_items} items processed "
            f"({self.success_count} success, {self.failure_count} failure) "
            f"in {elapsed} ({items_per_second: .2f} items/s)"
        )


def get_logger(name: str) -> logging.Logger:
    """
    Get logger for module.

    Args:
        name: Module name

    Returns:
        Logger for module
    """
    return logging.getLogger(name)

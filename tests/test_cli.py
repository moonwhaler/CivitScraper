"""
Tests for the command-line interface.

This module contains tests for the CLI functionality.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from civitscraper.cli import main, parse_args


def test_parse_args():
    """Test parsing command-line arguments."""
    # Test with no arguments
    with patch("sys.argv", ["civitscraper"]):
        args = parse_args()
        assert args.config is None
        assert args.job is None
        assert not args.all_jobs
        assert not args.dry_run
        assert not args.force_refresh
        assert not args.debug
        assert not args.quiet

    # Test with all arguments
    with patch(
        "sys.argv",
        [
            "civitscraper",
            "--config",
            "test_config.yaml",
            "--job",
            "test_job",
            "--all-jobs",
            "--dry-run",
            "--force-refresh",
            "--debug",
            "--quiet",
        ],
    ):
        args = parse_args()
        assert args.config == "test_config.yaml"
        assert args.job == "test_job"
        assert args.all_jobs
        assert args.dry_run
        assert args.force_refresh
        assert args.debug
        assert args.quiet


@patch("civitscraper.cli.load_and_validate_config")
@patch("civitscraper.cli.CivitAIClient")
@patch("civitscraper.cli.JobExecutor")
@patch("civitscraper.cli.setup_logging")
def test_main_with_specific_job(
    mock_setup_logging, mock_job_executor, mock_client, mock_load_config
):
    """
    Test running the main function with a specific job.

    Args:
        mock_setup_logging: Mock for the setup_logging function
        mock_job_executor: Mock for the JobExecutor class
        mock_client: Mock for the CivitAIClient class
        mock_load_config: Mock for the load_and_validate_config function
    """
    # Mock configuration
    mock_config = {"api": {"key": "test_key"}, "logging": {"level": "INFO"}}
    mock_load_config.return_value = mock_config

    # Mock job executor
    mock_executor_instance = mock_job_executor.return_value
    mock_executor_instance.execute_job.return_value = True

    # Mock logger
    mock_logger = MagicMock()
    mock_setup_logging.return_value = mock_logger

    # Run with a specific job
    with patch("sys.argv", ["civitscraper", "--job", "test_job"]):
        result = main()

        # Verify the result
        assert result == 0

        # Verify the mocks were called correctly
        mock_load_config.assert_called_once()
        mock_client.assert_called_once_with(mock_config)
        mock_job_executor.assert_called_once()
        mock_executor_instance.execute_job.assert_called_once_with("test_job")


@patch("civitscraper.cli.load_and_validate_config")
@patch("civitscraper.cli.CivitAIClient")
@patch("civitscraper.cli.JobExecutor")
@patch("civitscraper.cli.setup_logging")
def test_main_with_all_jobs(mock_setup_logging, mock_job_executor, mock_client, mock_load_config):
    """
    Test running the main function with all jobs.

    Args:
        mock_setup_logging: Mock for the setup_logging function
        mock_job_executor: Mock for the JobExecutor class
        mock_client: Mock for the CivitAIClient class
        mock_load_config: Mock for the load_and_validate_config function
    """
    # Mock configuration
    mock_config = {"api": {"key": "test_key"}, "logging": {"level": "INFO"}}
    mock_load_config.return_value = mock_config

    # Mock job executor
    mock_executor_instance = mock_job_executor.return_value
    mock_executor_instance.execute_all_jobs.return_value = {"job1": True, "job2": True}

    # Mock logger
    mock_logger = MagicMock()
    mock_setup_logging.return_value = mock_logger

    # Run with all jobs
    with patch("sys.argv", ["civitscraper", "--all-jobs"]):
        result = main()

        # Verify the result
        assert result == 0

        # Verify the mocks were called correctly
        mock_load_config.assert_called_once()
        mock_client.assert_called_once_with(mock_config)
        mock_job_executor.assert_called_once()
        mock_executor_instance.execute_all_jobs.assert_called_once()


@patch("civitscraper.cli.load_and_validate_config")
@patch("civitscraper.cli.CivitAIClient")
@patch("civitscraper.cli.JobExecutor")
@patch("civitscraper.cli.setup_logging")
def test_main_with_default_job(
    mock_setup_logging, mock_job_executor, mock_client, mock_load_config
):
    """
    Test running the main function with the default job.

    Args:
        mock_setup_logging: Mock for the setup_logging function
        mock_job_executor: Mock for the JobExecutor class
        mock_client: Mock for the CivitAIClient class
        mock_load_config: Mock for the load_and_validate_config function
    """
    # Mock configuration with a default job
    mock_config = {
        "api": {"key": "test_key"},
        "logging": {"level": "INFO"},
        "default_job": "default_job",
    }
    mock_load_config.return_value = mock_config

    # Mock job executor
    mock_executor_instance = mock_job_executor.return_value
    mock_executor_instance.execute_job.return_value = True

    # Mock logger
    mock_logger = MagicMock()
    mock_setup_logging.return_value = mock_logger

    # Run with no job specified (should use default)
    with patch("sys.argv", ["civitscraper"]):
        result = main()

        # Verify the result
        assert result == 0

        # Verify the mocks were called correctly
        mock_load_config.assert_called_once()
        mock_client.assert_called_once_with(mock_config)
        mock_job_executor.assert_called_once()
        mock_executor_instance.execute_job.assert_called_once_with("default_job")


@patch("civitscraper.cli.load_and_validate_config")
@patch("civitscraper.cli.logging.getLogger")
def test_main_with_exception(mock_get_logger, mock_load_config):
    """
    Test running the main function with an exception.

    Args:
        mock_get_logger: Mock for the getLogger function
        mock_load_config: Mock for the load_and_validate_config function
    """
    # Mock configuration loading to raise an exception
    mock_load_config.side_effect = Exception("Test exception")

    # Mock logger
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger

    # Run with an exception
    with patch("sys.argv", ["civitscraper"]):
        result = main()

        # Verify the result
        assert result == 1

        # Verify the logger was called with the error
        mock_logger.error.assert_called_once()
        assert "Test exception" in mock_logger.error.call_args[0][0]

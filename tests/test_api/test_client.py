"""
Tests for the CivitAI API client.

This module contains tests for the CivitAI API client functionality.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from civitscraper.api.client import CivitAIClient
from civitscraper.api.exceptions import ClientError, RateLimitError


@pytest.fixture
def api_client(sample_config):
    """
    Create a CivitAIClient instance for testing.

    Args:
        sample_config: The sample configuration dictionary

    Returns:
        CivitAIClient: An instance of the CivitAI API client
    """
    return CivitAIClient(sample_config)


def test_client_initialization(api_client, sample_config):
    """
    Test client initialization with configuration.

    Args:
        api_client: The API client instance
        sample_config: The sample configuration dictionary
    """
    assert api_client.api_key == sample_config["api"]["key"]
    assert api_client.base_url == sample_config["api"]["base_url"]
    assert api_client.timeout == sample_config["api"]["timeout"]
    assert api_client.max_retries == sample_config["api"]["max_retries"]
    assert api_client.user_agent == sample_config["api"]["user_agent"]


@patch("civitscraper.api.request.RequestHandler.request")
def test_get_model_by_id_success(mock_request, api_client):
    """
    Test getting a model by ID with a successful response.

    Args:
        mock_request: Mock for the RequestHandler.request method
        api_client: The API client instance
    """
    # Mock response
    response_data = {"id": 123, "name": "Test Model"}
    mock_request.return_value = json.dumps(response_data)

    # Call the method
    result = api_client.get_model(123)

    # Verify the result
    assert result["id"] == 123
    assert result["name"] == "Test Model"

    # Verify the request was made correctly
    mock_request.assert_called_once_with(
        method="GET", endpoint=f"models/123", params=None, data=None, force_refresh=False
    )


@patch("civitscraper.api.request.RequestHandler.request")
def test_get_model_by_id_not_found(mock_request, api_client):
    """
    Test getting a model by ID with a not found response.

    Args:
        mock_request: Mock for the RequestHandler.request method
        api_client: The API client instance
    """
    # Set up the mock to raise a ClientError
    error_message = "Model not found"
    mock_request.side_effect = ClientError(404, error_message)

    # Call the method and expect an exception
    with pytest.raises(ClientError) as excinfo:
        api_client.get_model(999)

    # Verify the exception
    assert "404" in str(excinfo.value)
    assert "Model not found" in str(excinfo.value)


@patch("civitscraper.api.request.RequestHandler.request")
def test_get_model_by_id_rate_limited(mock_request, api_client):
    """
    Test getting a model by ID with a rate limited response.

    Args:
        mock_request: Mock for the RequestHandler.request method
        api_client: The API client instance
    """
    # Set up the mock to raise a RateLimitError
    retry_after = 30
    mock_request.side_effect = RateLimitError(retry_after)

    # Call the method and expect an exception
    with pytest.raises(RateLimitError) as excinfo:
        api_client.get_model(123)

    # Verify the exception
    assert str(retry_after) in str(excinfo.value)
    assert "Rate limit exceeded" in str(excinfo.value)


@patch("civitscraper.api.request.RequestHandler.request")
def test_get_model_by_hash_success(mock_request, api_client):
    """
    Test getting a model by hash with a successful response.

    Args:
        mock_request: Mock for the RequestHandler.request method
        api_client: The API client instance
    """
    # Mock response
    response_data = {"items": [{"id": 123, "name": "Test Model"}]}
    mock_request.return_value = json.dumps(response_data)

    # Call the method
    result = api_client.get_model_by_hash("testhash123")

    # Verify the result
    assert result["id"] == 123
    assert result["name"] == "Test Model"

    # Verify the request was made correctly
    mock_request.assert_called_once_with(
        method="GET",
        endpoint="models",
        params={"hashes[]": "testhash123"},
        data=None,
        force_refresh=False,
    )


@patch("civitscraper.api.request.RequestHandler.request")
def test_get_model_by_hash_not_found(mock_request, api_client):
    """
    Test getting a model by hash with no results.

    Args:
        mock_request: Mock for the RequestHandler.request method
        api_client: The API client instance
    """
    # Mock response
    response_data = {"items": []}
    mock_request.return_value = json.dumps(response_data)

    # Call the method
    result = api_client.get_model_by_hash("nonexistenthash")

    # Verify the result is None
    assert result is None

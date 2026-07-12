"""Tests that the images endpoint forwards the nsfw browsing-level parameter."""

from unittest.mock import MagicMock

from civitscraper.api.endpoints.images import ImagesEndpoint


def make_endpoint():
    base = MagicMock()
    base._make_request.return_value = {"items": []}
    return ImagesEndpoint(base), base


def test_get_forwards_nsfw_param():
    endpoint, base = make_endpoint()
    endpoint.get(model_version_id=11745, nsfw="X")
    _, kwargs = base._make_request.call_args
    assert kwargs["params"]["nsfw"] == "X"
    assert kwargs["params"]["modelVersionId"] == 11745


def test_get_omits_nsfw_when_none():
    endpoint, base = make_endpoint()
    endpoint.get(model_version_id=11745)
    _, kwargs = base._make_request.call_args
    assert "nsfw" not in kwargs["params"]

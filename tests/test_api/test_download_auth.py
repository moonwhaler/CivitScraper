"""The API key must only be sent to the API host; downloads have their own limiter."""

from unittest.mock import MagicMock

import pytest

from civitscraper.api.base_client import BaseClient


def client(tmp_path):
    config = {
        "api": {
            "base_url": "https://civitai.com/api/v1",
            "key": "secret-key",
            "batch": {"rate_limit": 60, "download_rate_limit": 600},
        },
        "scanner": {"cache_dir": str(tmp_path)},
    }
    base = BaseClient(config)
    handler = base.request_handler
    response = MagicMock()
    response.headers = {"Content-Type": "image/jpeg"}
    response.iter_content.return_value = [b"img"]
    handler.session.get = MagicMock(return_value=response)
    return base, handler


@pytest.mark.parametrize(
    "url",
    ["https://image.civitai.com/x/1.jpeg", "https://evil.example/steal.jpeg"],
)
def test_no_api_key_sent_to_other_hosts(tmp_path, url):
    _, handler = client(tmp_path)

    ok, _ = handler.download(url, str(tmp_path / "p.jpeg"))

    assert ok
    assert handler.session.get.call_args.kwargs["headers"] == {"Authorization": None}
    # Session still carries the key for API requests
    assert handler.session.headers["Authorization"] == "Bearer secret-key"


def test_api_host_downloads_keep_auth(tmp_path):
    _, handler = client(tmp_path)

    handler.download("https://civitai.com/api/download/models/1", str(tmp_path / "m.bin"))

    assert handler.session.get.call_args.kwargs["headers"] is None


def test_downloads_use_their_own_rate_limiter(tmp_path):
    base, handler = client(tmp_path)

    assert handler.download_rate_limiter is base.download_rate_limiter
    assert handler.download_rate_limiter is not handler.rate_limiter
    api_tokens = handler.rate_limiter.get_tokens()
    handler.download("https://image.civitai.com/x/1.jpeg", str(tmp_path / "p.jpeg"))
    assert handler.rate_limiter.get_tokens() >= api_tokens

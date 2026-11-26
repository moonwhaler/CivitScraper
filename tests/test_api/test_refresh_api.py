"""Version endpoint, parent-model errors and rate limiting of retries."""

from unittest.mock import MagicMock

import pytest

from civitscraper.api.client import CivitAIClient
from civitscraper.api.exceptions import ClientError, NetworkError, ServerError
from civitscraper.api.request import RequestHandler
from civitscraper.scanner.version_enricher import VersionEnricher


def _client(tmp_path):
    return CivitAIClient({"api": {"base_url": "https://civitai.com/api/v1"},
                          "scanner": {"cache_dir": str(tmp_path)}})


def test_get_model_version_calls_the_version_endpoint(tmp_path):
    client = _client(tmp_path)
    client._base_client._make_request = MagicMock(return_value={"id": 7})
    assert client.get_model_version(7)["id"] == 7
    assert client._base_client._make_request.call_args.kwargs["endpoint"] == "model-versions/7"


def test_parent_model_none_only_for_404(tmp_path):
    client = _client(tmp_path)
    client.get_model = MagicMock(side_effect=ClientError(404, "gone"))
    assert client.get_parent_model_with_versions(1, 0) is None
    client.get_model = MagicMock(side_effect=ServerError(503, "down"))
    with pytest.raises(ServerError):
        client.get_parent_model_with_versions(1, 0)
    client.get_model = MagicMock(return_value={})
    with pytest.raises(ValueError):
        client.get_parent_model_with_versions(1, 0)


def _meta(model_id):
    return {"id": model_id * 10, "modelId": model_id}


def test_enricher_caches_only_real_404s_and_survives_errors(tmp_path):
    api = MagicMock()

    def parent(model_id, current_version_id=0, force_refresh=False):
        if model_id == 1:
            return None  # 404
        raise NetworkError("timeout")

    api.get_parent_model_with_versions.side_effect = parent
    config = {"scanner": {"cache_dir": str(tmp_path)}}
    enricher = VersionEnricher(api, config)
    enricher.enrich_batch({"a": _meta(1), "b": _meta(2)})  # must not raise

    assert enricher.removed_models == {1}
    fresh = VersionEnricher(api, config)
    assert fresh._is_model_known_failed(1)
    assert not fresh._is_model_known_failed(2)  # a timeout is not remembered


def test_old_failed_model_cache_is_ignored(tmp_path):
    from civitscraper.utils.cache import DiskCache

    DiskCache[bool](str(tmp_path / "failed_models")).set("failed_model_3", True)
    assert not VersionEnricher(MagicMock(), {"scanner": {"cache_dir": str(tmp_path)}}
                               )._is_model_known_failed(3)


def test_every_retry_takes_a_rate_limit_token():
    limiter = MagicMock()
    breaker = MagicMock()
    breaker.is_open.return_value = False
    handler = RequestHandler("https://civitai.com/api/v1", limiter, breaker,
                             max_retries=2, base_retry_delay=0)
    response = MagicMock(status_code=503, text="down")
    handler.session.request = MagicMock(return_value=response)
    with pytest.raises(ServerError):
        handler.request("GET", "models/1")
    assert limiter.acquire.call_count == 3

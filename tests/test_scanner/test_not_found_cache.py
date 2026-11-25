"""Hashes CivitAI does not know are remembered; transient errors are not."""

import os
import time
from unittest.mock import MagicMock

import pytest

from civitscraper.api.exceptions import ClientError, NetworkError, ServerError
from civitscraper.scanner.metadata_manager import MetadataManager


def manager(tmp_path, error, validity=None):
    scanner = {"cache_dir": str(tmp_path)}
    if validity is not None:
        scanner["not_found_validity"] = validity
    api = MagicMock()
    api.get_model_version_by_hash.side_effect = error
    return MetadataManager({"scanner": scanner}, api), api


def test_404_is_remembered_across_runs(tmp_path):
    first, api = manager(tmp_path, ClientError(404, "not found"))
    assert first.fetch_metadata("ABC") is None

    second, api2 = manager(tmp_path, ClientError(404, "not found"))
    assert second.is_known_not_found("ABC")
    assert second.fetch_metadata("ABC") is None
    api2.get_model_version_by_hash.assert_not_called()


@pytest.mark.parametrize(
    "error", [ServerError(503, "down"), NetworkError("timeout"), ClientError(429, "slow down")]
)
def test_transient_errors_are_not_remembered(tmp_path, error):
    first, _ = manager(tmp_path, error)
    assert first.fetch_metadata("ABC") is None
    assert not first.is_known_not_found("ABC")


def test_force_refresh_bypasses_negative_cache(tmp_path):
    first, _ = manager(tmp_path, ClientError(404, "not found"))
    first.fetch_metadata("ABC")
    second, api = manager(tmp_path, None)
    api.get_model_version_by_hash.side_effect = None
    api.get_model_version_by_hash.return_value = {"id": 1, "images": []}

    assert second.fetch_metadata("ABC", force_refresh=True)["id"] == 1


def test_negative_cache_expires(tmp_path):
    first, _ = manager(tmp_path, ClientError(404, "not found"), validity=60)
    first.fetch_metadata("ABC")
    for f in (tmp_path / "not_found").iterdir():
        old = time.time() - 120
        os.utime(f, (old, old))

    second, _ = manager(tmp_path, ClientError(404, "x"), validity=60)
    assert not second.is_known_not_found("ABC")

"""Tests for sibling-version TTL refresh and dirty-marker persistence."""

import json
import os
import time
from unittest.mock import MagicMock

import pytest

from civitscraper.scanner.metadata_manager import MetadataManager
from civitscraper.scanner.version_enricher import (
    DIRTY_FLAG,
    SIBLING_VERSIONS_TS_FIELD,
    VersionEnricher,
)


def make_enricher(tmp_path, ttl=86400):
    """Build a VersionEnricher with a mocked API client and isolated cache dir."""
    api = MagicMock()
    config = {
        "scanner": {
            "cache_dir": str(tmp_path / "cache"),
            "version_cache_validity": ttl,
        }
    }
    return VersionEnricher(api, config), api


def parent_payload(model_id=10, version_ids=(100, 101)):
    """Shape returned by api_client.get_parent_model_with_versions."""
    return {
        "parentModel": {"id": model_id, "name": "M"},
        "siblingVersions": [{"id": vid, "name": f"v{vid}"} for vid in version_ids],
    }


# --------------------------------------------------------------------------- #
# needs_enrichment / _siblings_expired matrix
# --------------------------------------------------------------------------- #


def test_needs_enrichment_missing_siblings(tmp_path):
    enricher, _ = make_enricher(tmp_path)
    assert enricher.needs_enrichment({"modelId": 1}) is True


def test_needs_enrichment_fresh(tmp_path):
    enricher, _ = make_enricher(tmp_path, ttl=86400)
    meta = {"siblingVersions": [{"id": 1}], SIBLING_VERSIONS_TS_FIELD: time.time()}
    assert enricher.needs_enrichment(meta) is False


def test_needs_enrichment_expired(tmp_path):
    enricher, _ = make_enricher(tmp_path, ttl=100)
    meta = {"siblingVersions": [{"id": 1}], SIBLING_VERSIONS_TS_FIELD: time.time() - 1000}
    assert enricher.needs_enrichment(meta) is True


def test_needs_enrichment_legacy_no_timestamp(tmp_path):
    enricher, _ = make_enricher(tmp_path)
    meta = {"siblingVersions": [{"id": 1}]}  # no timestamp = legacy sidecar
    assert enricher.needs_enrichment(meta) is True


def test_needs_enrichment_force_refresh(tmp_path):
    enricher, _ = make_enricher(tmp_path)
    meta = {"siblingVersions": [{"id": 1}], SIBLING_VERSIONS_TS_FIELD: time.time()}
    assert enricher.needs_enrichment(meta, force_refresh=True) is True


def test_needs_enrichment_ttl_zero_always_stale(tmp_path):
    enricher, _ = make_enricher(tmp_path, ttl=0)
    meta = {"siblingVersions": [{"id": 1}], SIBLING_VERSIONS_TS_FIELD: time.time()}
    assert enricher.needs_enrichment(meta) is True


def test_siblings_expired_missing_is_not_expired(tmp_path):
    enricher, _ = make_enricher(tmp_path)
    # No siblings at all is "never enriched", not "expired".
    assert enricher._siblings_expired({"modelId": 1}) is False


# --------------------------------------------------------------------------- #
# enrich_batch: stamping, dirty marker, force_models HTTP-cache bypass
# --------------------------------------------------------------------------- #


def test_enrich_batch_stamps_and_marks_dirty(tmp_path):
    enricher, api = make_enricher(tmp_path)
    api.get_parent_model_with_versions.return_value = parent_payload(version_ids=(100, 101))

    meta = {"id": 100, "modelId": 10}  # first-time, no siblings
    result = enricher.enrich_batch({"/f.safetensors": meta})

    enriched = result["/f.safetensors"]
    assert len(enriched["siblingVersions"]) == 2
    assert isinstance(enriched[SIBLING_VERSIONS_TS_FIELD], (int, float))
    assert enriched[DIRTY_FLAG] is True


def test_enrich_batch_skips_fresh(tmp_path):
    enricher, api = make_enricher(tmp_path, ttl=86400)
    meta = {"id": 100, "modelId": 10, "siblingVersions": [{"id": 100}],
            SIBLING_VERSIONS_TS_FIELD: time.time()}
    enricher.enrich_batch({"/f.safetensors": meta})
    api.get_parent_model_with_versions.assert_not_called()


def test_enrich_batch_first_time_uses_cached_fetch(tmp_path):
    enricher, api = make_enricher(tmp_path)
    api.get_parent_model_with_versions.return_value = parent_payload()
    meta = {"id": 100, "modelId": 10}  # missing siblings => not "expired"
    enricher.enrich_batch({"/f.safetensors": meta})
    _, kwargs = api.get_parent_model_with_versions.call_args
    assert kwargs["force_refresh"] is False


def test_enrich_batch_stale_forces_http_cache_bypass(tmp_path):
    enricher, api = make_enricher(tmp_path, ttl=100)
    api.get_parent_model_with_versions.return_value = parent_payload()
    meta = {"id": 100, "modelId": 10, "siblingVersions": [{"id": 100}],
            SIBLING_VERSIONS_TS_FIELD: time.time() - 1000}  # present but stale
    enricher.enrich_batch({"/f.safetensors": meta})
    _, kwargs = api.get_parent_model_with_versions.call_args
    assert kwargs["force_refresh"] is True


def test_enrich_batch_shared_model_union_forces_when_any_stale(tmp_path):
    enricher, api = make_enricher(tmp_path, ttl=100)
    api.get_parent_model_with_versions.return_value = parent_payload()
    # Two files share modelId 10: one first-time-missing, one present-but-stale.
    missing = {"id": 100, "modelId": 10}
    stale = {"id": 101, "modelId": 10, "siblingVersions": [{"id": 101}],
             SIBLING_VERSIONS_TS_FIELD: time.time() - 1000}
    enricher.enrich_batch({"/a.safetensors": missing, "/b.safetensors": stale})
    # Model fetched once, forced because at least one contributor is stale.
    assert api.get_parent_model_with_versions.call_count == 1
    _, kwargs = api.get_parent_model_with_versions.call_args
    assert kwargs["force_refresh"] is True


# --------------------------------------------------------------------------- #
# save_metadata: dirty marker bypasses skip_existing and is never serialized
# --------------------------------------------------------------------------- #


def metadata_manager(skip_existing):
    config = {
        "skip_existing": skip_existing,
        "output": {"metadata": {"path": "{model_dir}", "filename": "{model_name}.json"}},
    }
    return MetadataManager(config, MagicMock())


def test_save_metadata_dirty_overwrites_under_skip_existing(tmp_path):
    model = tmp_path / "model.safetensors"
    model.write_text("x")
    sidecar = tmp_path / "model.json"
    sidecar.write_text(json.dumps({"old": True}))

    mm = metadata_manager(skip_existing=True)
    assert mm.save_metadata(str(model), {"new": True, DIRTY_FLAG: True}) is True

    written = json.loads(sidecar.read_text())
    assert written == {"new": True}  # overwritten and marker stripped
    assert DIRTY_FLAG not in written


def test_save_metadata_non_dirty_skips_under_skip_existing(tmp_path):
    model = tmp_path / "model.safetensors"
    model.write_text("x")
    sidecar = tmp_path / "model.json"
    sidecar.write_text(json.dumps({"old": True}))

    mm = metadata_manager(skip_existing=True)
    assert mm.save_metadata(str(model), {"new": True}) is True

    assert json.loads(sidecar.read_text()) == {"old": True}  # untouched

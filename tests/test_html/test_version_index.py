"""Tests for VersionIndexCache per-model version union (detail-page consistency)."""

import json

from civitscraper.html.context import (
    ContextBuilder,
    VersionIndexCache,
    invalidate_version_index,
)

_CB_CONFIG = {
    "output": {
        "metadata": {
            "path": "{model_dir}",
            "filename": "{model_name}.json",
            "html": {"filename": "{model_name}.html"},
        }
    }
}


def write_sidecar(directory, name, version_id, model_id, siblings, download_count=0,
                  created="2024-01-01T00:00:00Z", base_model="SD 1.5"):
    """Write a model sidecar .json into directory and return its path."""
    data = {
        "id": version_id,
        "modelId": model_id,
        "name": name,
        "baseModel": base_model,
        "createdAt": created,
        "stats": {"downloadCount": download_count},
        "siblingVersions": siblings,
    }
    path = directory / f"{name}.json"
    path.write_text(json.dumps(data))
    return path


def test_union_merges_drifted_sidecars(tmp_path):
    """Two local versions with DIFFERENT stale sibling lists -> complete union."""
    # Version A sidecar only knows about A and B (stale, missing C).
    write_sidecar(tmp_path, "A", 100, 10,
                  siblings=[{"id": 100, "name": "A"}, {"id": 101, "name": "B"}],
                  created="2024-01-01T00:00:00Z")
    # Version B sidecar knows A, B, and a remote-only D.
    write_sidecar(tmp_path, "B", 101, 10,
                  siblings=[{"id": 100, "name": "A"}, {"id": 101, "name": "B"},
                            {"id": 102, "name": "D", "createdAt": "2024-03-01T00:00:00Z"}],
                  created="2024-02-01T00:00:00Z")

    cache = VersionIndexCache()
    versions = cache.get_model_versions(str(tmp_path), model_id=10, current_version_id=100)

    by_id = {v["id"]: v for v in versions}
    # Union contains every version any sidecar referenced: A, B (local) + D (remote).
    assert set(by_id) == {100, 101, 102}
    assert by_id[100]["is_local"] is True   # A: sidecar present
    assert by_id[101]["is_local"] is True   # B: sidecar present
    assert by_id[102]["is_local"] is False  # D: remote-only
    assert by_id[102]["link"] == "https://civitai.com/models/10?modelVersionId=102"


def test_union_is_identical_regardless_of_current_version(tmp_path):
    """The set of versions is the same on every page; only isCurrent shifts."""
    write_sidecar(tmp_path, "A", 100, 10, siblings=[{"id": 100}, {"id": 101}])
    write_sidecar(tmp_path, "B", 101, 10, siblings=[{"id": 100}, {"id": 101}])

    cache = VersionIndexCache()
    from_a = cache.get_model_versions(str(tmp_path), 10, 100)
    cache.invalidate()
    from_b = cache.get_model_versions(str(tmp_path), 10, 101)

    assert {v["id"] for v in from_a} == {v["id"] for v in from_b} == {100, 101}
    assert {v["id"] for v in from_a if v["isCurrent"]} == {100}
    assert {v["id"] for v in from_b if v["isCurrent"]} == {101}


def test_local_detection_without_existing_html(tmp_path):
    """Sidecar present but no .html on disk -> still local, link to computed path."""
    write_sidecar(tmp_path, "A", 100, 10, siblings=[{"id": 100}])
    cache = VersionIndexCache()
    versions = cache.get_model_versions(str(tmp_path), 10, 100)
    assert versions[0]["is_local"] is True
    assert versions[0]["link"].endswith("A.html")


def test_local_download_count_comes_from_stats(tmp_path):
    """downloadCount for a local-only version is sourced from stats.downloadCount."""
    # Single local version, no siblings -> its only data source is its own sidecar.
    write_sidecar(tmp_path, "A", 100, 10, siblings=[], download_count=42)
    cache = VersionIndexCache()
    versions = cache.get_model_versions(str(tmp_path), 10, 100)
    assert versions[0]["downloadCount"] == 42
    assert versions[0]["baseModel"] == "SD 1.5"
    assert versions[0]["name"] == "A"


def test_single_local_no_remote_returns_length_one(tmp_path):
    """1 local + 0 remote -> length-1 list (detail template hides 'Other Versions')."""
    write_sidecar(tmp_path, "A", 100, 10, siblings=[])
    cache = VersionIndexCache()
    versions = cache.get_model_versions(str(tmp_path), 10, 100)
    assert len(versions) == 1


def test_get_model_versions_empty_for_unknown_model(tmp_path):
    """No sidecar for the model -> empty (caller falls back to per-file snapshot)."""
    write_sidecar(tmp_path, "A", 100, 10, siblings=[{"id": 100}])
    cache = VersionIndexCache()
    assert cache.get_model_versions(str(tmp_path), model_id=999, current_version_id=1) == []
    assert cache.get_model_versions(str(tmp_path), model_id=None, current_version_id=1) == []


def test_get_html_path_no_isfile_requirement(tmp_path):
    """get_html_path returns a computed path from sidecar presence alone."""
    write_sidecar(tmp_path, "A", 100, 10, siblings=[])
    cache = VersionIndexCache()
    assert cache.get_html_path(str(tmp_path), 100).endswith("A.html")
    assert cache.get_html_path(str(tmp_path), 999) is None


def test_build_sibling_versions_context_uses_union(tmp_path):
    """With a modelId, the detail context is built from the directory union."""
    write_sidecar(tmp_path, "A", 100, 10, siblings=[{"id": 100}, {"id": 101}])
    write_sidecar(tmp_path, "B", 101, 10,
                  siblings=[{"id": 100}, {"id": 101}, {"id": 102, "name": "D"}])
    invalidate_version_index()  # global cache used by ContextBuilder

    cb = ContextBuilder(_CB_CONFIG)
    versions = cb._build_sibling_versions_context(
        str(tmp_path / "A.safetensors"),
        sibling_versions=[{"id": 100}, {"id": 101}],  # A's stale snapshot (missing D)
        parent_model_id=10,
        current_version_id=100,
    )
    # Union surfaces D even though A's own snapshot lacked it.
    assert {v["id"] for v in versions} == {100, 101, 102}
    invalidate_version_index()


def test_build_sibling_versions_context_fallback_without_model_id(tmp_path):
    """Without a modelId, falls back to the file's own snapshot (no regression)."""
    invalidate_version_index()
    cb = ContextBuilder(_CB_CONFIG)
    versions = cb._build_sibling_versions_context(
        str(tmp_path / "A.safetensors"),
        sibling_versions=[{"id": 100, "name": "A"}, {"id": 101, "name": "B"}],
        parent_model_id=None,
        current_version_id=100,
    )
    assert {v["id"] for v in versions} == {100, 101}
    # Remote fallback link form (no local sidecars on disk).
    assert all(v["is_local"] is False for v in versions)

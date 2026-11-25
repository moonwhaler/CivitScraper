"""Parallel hash + lookup honors api.batch.max_concurrent and loses nothing."""

import os
import threading
import time
from unittest.mock import MagicMock

import pytest

from civitscraper.jobs.executor import JobExecutor


def run_job(tmp_path, monkeypatch, n, hash_workers, max_concurrent, enabled=True):
    monkeypatch.chdir(tmp_path)
    models = tmp_path / "loras"
    models.mkdir()
    for i in range(n):
        (models / f"m{i:03d}.safetensors").write_bytes(f"w{i}".encode())

    state = {"active": 0, "peak": 0, "calls": 0}
    lock = threading.Lock()

    def by_hash(h, force_refresh=False):
        with lock:
            state["active"] += 1
            state["calls"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.02)
        with lock:
            state["active"] -= 1
        return {"id": int(h[:6], 16), "modelId": 1, "images": []}

    api = MagicMock()
    api.get_model_version_by_hash.side_effect = by_hash
    api.get_parent_model_with_versions.return_value = None
    config = {
        "api": {
            "base_url": "https://example.invalid",
            "batch": {"enabled": enabled, "max_concurrent": max_concurrent},
        },
        "scanner": {"cache_dir": str(tmp_path / "cache"), "hash_workers": hash_workers},
        "input_paths": {"l": {"path": str(models), "type": "LORA", "patterns": ["*.safetensors"]}},
        "jobs": {
            "scan": {
                "type": "scan-paths",
                "paths": ["l"],
                "output": {"metadata": {"html": {"enabled": False}}, "images": {"save": False}},
            }
        },
    }
    assert JobExecutor(config, api).execute_job("scan")
    sidecars = [f for f in os.listdir(models) if f.endswith(".json")]
    return state, sidecars


def test_api_concurrency_bounded_by_max_concurrent(tmp_path, monkeypatch):
    state, sidecars = run_job(tmp_path, monkeypatch, n=24, hash_workers=8, max_concurrent=3)

    assert state["calls"] == 24
    assert len(sidecars) == 24
    assert 1 < state["peak"] <= 3


@pytest.mark.parametrize("kwargs", [{"hash_workers": 1}, {"hash_workers": 8, "enabled": False}])
def test_sequential_when_one_worker_or_batch_disabled(tmp_path, monkeypatch, kwargs):
    state, sidecars = run_job(tmp_path, monkeypatch, n=6, max_concurrent=4, **kwargs)

    assert state["peak"] == 1
    assert len(sidecars) == 6

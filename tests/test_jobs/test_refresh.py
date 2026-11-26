"""Refreshing known models: due selection, merging, removed flags, nothing deleted."""

import json
import os
import time
from unittest.mock import MagicMock

import pytest

from civitscraper.api.exceptions import ClientError, NetworkError
from civitscraper.jobs.scan_job import ScanJob
from civitscraper.scanner.sidecar import NAMESPACE

DAY = 86400


def img(n):
    return {"url": f"https://image.civitai.com/key/uuid-{n}/original=true/{n}.jpeg",
            "meta": {"prompt": f"prompt {n}"}}


def version(vid, images, **extra):
    return {"id": vid, "modelId": vid * 10, "name": "v1", "images": images,
            "model": {"name": f"M{vid}", "type": "LORA"}, "stats": {"downloadCount": 1}, **extra}


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    models = tmp_path / "loras"
    models.mkdir()
    config = {
        "api": {"base_url": "https://example.invalid"},
        "scanner": {"cache_dir": str(tmp_path / "cache")},
        "input_paths": {"l": {"path": str(models), "type": "LORA",
                              "patterns": ["*.safetensors"]}},
    }
    api = MagicMock()
    api.get_parent_model_with_versions.side_effect = lambda mid, current_version_id=0, \
        force_refresh=False: {"parentModel": {"id": mid, "name": "P", "tags": ["fresh"]},
                              "siblingVersions": [{"id": mid // 10, "name": "v1"}]}

    def download(url, path):
        with open(path, "wb") as f:
            f.write(b"new " + url.rsplit("/", 1)[1].encode())
        return True, "image/jpeg"

    api.download_image.side_effect = download
    return config, models, api


def add_model(models, name, vid, images, age_days, files=(), **extra):
    (models / f"{name}.safetensors").write_bytes(name.encode())
    sidecar = version(vid, images, **extra)
    sidecar[NAMESPACE] = {"fetchedAt": time.time() - age_days * DAY,
                          "checkedAt": time.time() - age_days * DAY, "previewsSynced": True}
    path = models / f"{name}.json"
    path.write_text(json.dumps(sidecar))
    for n, tag in enumerate(files, 1):
        (models / f"{name}.preview{n}.jpeg").write_bytes(tag.encode())
    return path


def job(config, api, **job_extra):
    spec = {"type": "scan-paths", "paths": ["l"],
            "output": {"metadata": {"html": {"enabled": True}}, "images": {"max_count": 3}},
            **job_extra}
    return ScanJob(config, "fetch-all", spec, api)


def all_files(models):
    return sorted(os.listdir(models))


def test_due_files_oldest_first_and_capped(lib):
    config, models, api = lib
    add_model(models, "a", 1, [img(1)], 20)
    add_model(models, "b", 2, [img(2)], 30)
    add_model(models, "c", 3, [img(3)], 1)
    config["scanner"]["refresh_max_per_run"] = 1
    runner = job(config, api)
    assert runner.discover()
    assert [os.path.basename(f) for f in runner.refresh_files] == ["b.safetensors"]
    assert runner.filtered_files == []

    config["scanner"]["refresh_after_days"] = 0
    off = job(config, api)
    assert off.discover() and off.refresh_files == []
    cached = job(config, api, use_cached_metadata=True)
    assert cached.discover() and cached.refresh_files == []


def test_refresh_merges_reorders_previews_and_keeps_forge_keys(lib):
    config, models, api = lib
    sidecar = add_model(models, "a", 1, [img(1), img(2)], 20, files=("pic1", "pic2"),
                        **{"activation text": "my words", "notes": "mine"})
    api.get_model_version.return_value = version(1, [img(3), img(2)],
                                                 stats={"downloadCount": 99})
    runner = job(config, api)
    assert runner.run()

    data = json.loads(sidecar.read_text())
    assert data["activation text"] == "my words" and data["notes"] == "mine"
    assert data["stats"] == {"downloadCount": 99}
    assert data["parentModel"]["tags"] == ["fresh"]
    assert [i["meta"]["prompt"] for i in data["images"]] == ["prompt 3", "prompt 2", "prompt 1"]
    assert data["images"][2]["civitscraperArchived"] is True
    assert (models / "a.preview1.jpeg").read_bytes() == b"new 3.jpeg"
    assert (models / "a.preview2.jpeg").read_bytes() == b"pic2"
    assert (models / "a.preview3.jpeg").read_bytes() == b"pic1"  # archived, kept
    assert data[NAMESPACE]["fetchedAt"] > time.time() - 60
    assert runner.summary["refreshed"] == 1
    api.get_model_version.assert_called_once_with(1, force_refresh=True)
    api.get_model_version_by_hash.assert_not_called()  # no hashing for a refresh


def test_version_404_flags_and_deletes_nothing(lib):
    config, models, api = lib
    sidecar = add_model(models, "a", 1, [img(1)], 20, files=("pic1",))
    (models / "a.html").write_text("old page")
    before = json.loads(sidecar.read_text())
    api.get_model_version.side_effect = ClientError(404, "gone")
    runner = job(config, api)
    assert runner.run()

    data = json.loads(sidecar.read_text())
    assert data[NAMESPACE]["removed"]["what"] == "version"
    assert {k: v for k, v in data.items() if k not in (NAMESPACE, "parentModel",
                                                       "siblingVersions",
                                                       "siblingVersionsFetchedAt")} == {
        k: v for k, v in before.items() if k != NAMESPACE}
    assert (models / "a.preview1.jpeg").read_bytes() == b"pic1"
    assert (models / "a.html").read_text() != "old page"  # page regenerated, not removed
    assert runner.summary["removed"] == 1 and runner.summary["not_found"] == 0


def test_model_404_flags_every_file_of_the_model(lib):
    config, models, api = lib
    sidecar = add_model(models, "a", 1, [img(1)], 20, files=("pic1",))
    api.get_model_version.return_value = version(1, [img(1)])
    api.get_parent_model_with_versions.side_effect = None
    api.get_parent_model_with_versions.return_value = None  # 404
    assert job(config, api).run()
    data = json.loads(sidecar.read_text())
    assert data[NAMESPACE]["removed"]["what"] == "model"
    assert (models / "a.preview1.jpeg").read_bytes() == b"pic1"


def test_network_error_leaves_the_sidecar_untouched(lib):
    config, models, api = lib
    sidecar = add_model(models, "a", 1, [img(1)], 20, files=("pic1",))
    before = sidecar.read_bytes()
    files = all_files(models)
    api.get_model_version.side_effect = NetworkError("timeout")
    runner = job(config, api)
    assert runner.run()
    assert sidecar.read_bytes() == before
    assert runner.summary["errors"] == 1
    assert set(files) <= set(all_files(models))


def test_refusal_only_moves_the_check_date(lib):
    config, models, api = lib
    sidecar = add_model(models, "a", 1, [img(1)], 20)
    api.get_model_version.side_effect = ClientError(403, "early access")
    runner = job(config, api)
    assert runner.run()
    data = json.loads(sidecar.read_text())
    assert data[NAMESPACE]["checkedAt"] > time.time() - 60
    assert data[NAMESPACE]["fetchedAt"] < time.time() - 10 * DAY
    assert "removed" not in data[NAMESPACE]
    assert runner.summary["checked"] == 1


def test_forge_only_sidecar_is_looked_up_and_its_keys_kept(lib):
    config, models, api = lib
    (models / "f.safetensors").write_bytes(b"forge")
    (models / "f.json").write_text(json.dumps({"activation text": "forge words",
                                               "preferred weight": 0.7}))
    api.get_model_version_by_hash.return_value = version(5, [img(1)])
    runner = job(config, api)
    assert runner.discover() and [os.path.basename(f) for f in runner.filtered_files] == [
        "f.safetensors"]
    runner = job(config, api)
    assert runner.run()
    data = json.loads((models / "f.json").read_text())
    assert data["id"] == 5 and data["activation text"] == "forge words"
    assert data["preferred weight"] == 0.7
    assert runner.summary["new"] == 1


def test_full_rescan_404_on_a_known_file_flags_it(lib):
    config, models, api = lib
    sidecar = add_model(models, "a", 1, [img(1)], 1, files=("pic1",))
    api.get_model_version_by_hash.side_effect = ClientError(404, "gone")
    runner = job(config, api, skip_existing=False)
    assert runner.run()
    data = json.loads(sidecar.read_text())
    assert data[NAMESPACE]["removed"]["what"] == "version"
    assert data["images"] == [img(1)]
    assert runner.summary["removed"] == 1 and runner.summary["not_found"] == 0

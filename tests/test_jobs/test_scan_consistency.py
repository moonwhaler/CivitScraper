"""scan-paths phases agree on settings, and the summary tells failures apart."""

import json
import os
from unittest.mock import MagicMock

from civitscraper.api.exceptions import ServerError
from civitscraper.html.context import ContextBuilder
from civitscraper.jobs.scan_job import ScanJob
from civitscraper.scanner.discovery import get_metadata_path


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    models = tmp_path / "loras"
    models.mkdir()
    model = models / "foo.safetensors"
    model.write_bytes(b"x")
    config = {
        "api": {"base_url": "https://example.invalid"},
        "scanner": {"cache_dir": str(tmp_path / "cache")},
        "input_paths": {"l": {"path": str(models), "type": "LORA",
                              "patterns": ["*.safetensors"]}},
    }
    return config, models, str(model)


def _sidecar(config, model, **extra):
    path = get_metadata_path(model, config)
    data = {"id": 1, "modelId": 2, "name": "v1", "model": {"name": "Foo", "type": "LORA"},
            "images": [{"url": "https://image.civitai.com/x/a.jpeg"},
                       {"url": "https://image.civitai.com/x/b.jpeg"}], **extra}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def test_model_page_links_to_where_the_gallery_is_written(tmp_path, monkeypatch):
    config, _, model = _setup(tmp_path, monkeypatch)
    context = ContextBuilder(config).build_model_context(model, {"id": 1})
    html_dir = os.path.dirname(model)
    linked = os.path.normpath(os.path.join(html_dir, context["gallery_path"]))
    # ScanJob.build_gallery writes to gallery.html (working directory) by default
    assert linked == str(tmp_path / "gallery.html")


def test_gallery_path_from_global_config_is_used_by_the_gallery(tmp_path, monkeypatch):
    config, _, model = _setup(tmp_path, monkeypatch)
    _sidecar(config, model)
    config["output"] = {"metadata": {"html": {"gallery_path": str(tmp_path / "g" / "all.html"),
                                              "generate_gallery": True}}}
    job = {"type": "scan-paths", "paths": ["l"], "use_cached_metadata": True,
           "output": {"images": {"save": False}}}
    assert ScanJob(config, "regen", job, MagicMock()).run()
    assert (tmp_path / "g" / "all.html").is_file()


def test_cached_job_without_skip_existing_keeps_previews_and_sidecar(tmp_path, monkeypatch):
    """No skip_existing key: no preview is deleted or downloaded, no sidecar rewritten."""
    config, models, model = _setup(tmp_path, monkeypatch)
    sidecar = _sidecar(config, model)
    for i in (1, 2):
        (models / f"foo.preview{i}.jpeg").write_bytes(b"img")
    before = os.stat(sidecar).st_mtime_ns
    api = MagicMock()
    job = {"type": "scan-paths", "paths": ["l"], "use_cached_metadata": True,
           "output": {"metadata": {"html": {"enabled": True}}}}

    assert ScanJob(config, "regen", job, api).run()

    assert sorted(p.name for p in models.glob("foo.preview*")) == [
        "foo.preview1.jpeg", "foo.preview2.jpeg"]
    api.download_image.assert_not_called()
    assert os.stat(sidecar).st_mtime_ns == before
    assert (models / "foo.html").is_file()


def test_lookup_error_is_counted_as_error_not_as_not_found(tmp_path, monkeypatch):
    config, _, _ = _setup(tmp_path, monkeypatch)
    api = MagicMock()
    api.get_model_version_by_hash.side_effect = ServerError(503, "down")
    job_runner = ScanJob(config, "scan", {"type": "scan-paths", "paths": ["l"]}, api)

    assert job_runner.run()
    assert job_runner.summary["errors"] == 1
    assert job_runner.summary["not_found"] == 0


def test_sidecar_write_failure_skips_outputs_and_counts_as_failed(tmp_path, monkeypatch):
    config, models, model = _setup(tmp_path, monkeypatch)
    _sidecar(config, model)
    job = ScanJob(config, "regen", {"type": "scan-paths", "paths": ["l"],
                                     "use_cached_metadata": True, "skip_existing": False},
                  MagicMock())
    assert job.discover()
    job.fetch()
    job.processor.metadata_manager.save_metadata = MagicMock(return_value=False)
    job.write_sidecars()
    job.render()
    job.log_summary()

    assert job.summary["output_failed"] == 1
    assert not (models / "foo.html").exists()

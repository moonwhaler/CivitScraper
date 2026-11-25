"""Gallery card discovery: every model card once, with its model file."""

import json
import os
from unittest.mock import MagicMock

from civitscraper.html.context import ContextBuilder, model_file_extensions
from civitscraper.html.generator import HTMLGenerator
from civitscraper.jobs.scan_job import ScanJob
from civitscraper.scanner.discovery import find_html_files


def _card(directory, stem, ext, version_id, name):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{stem}{ext}").write_bytes(name.encode())
    (directory / f"{stem}.json").write_text(
        json.dumps({"id": version_id, "modelId": version_id * 10, "name": "v1",
                    "model": {"name": name, "type": "LORA"}})
    )
    (directory / f"{stem}.html").write_text("<html></html>")


def _config(tmp_path, patterns=("*.safetensors",)):
    lib = tmp_path / "Lora"
    lib.mkdir(exist_ok=True)
    return {
        "api": {"base_url": "https://example.invalid"},
        "scanner": {"cache_dir": str(tmp_path / "cache")},
        "input_paths": {"l": {"path": str(lib), "type": "LORA", "patterns": list(patterns)}},
        "gallery_path_ids": ["l"],
    }, lib


def _gallery_cards(tmp_path, config):
    out = tmp_path / "out" / "gallery.html"
    HTMLGenerator(config).generate_gallery([], str(out), include_existing=True)
    first_line = (tmp_path / "out" / "data" / "models_data.js").read_text().split("\n")[0]
    return json.loads(first_line.split("=", 1)[1].strip().rstrip(";"))


def test_same_named_cards_in_different_folders_are_all_listed(tmp_path):
    config, lib = _config(tmp_path)
    _card(lib / "A", "style", ".safetensors", 1, "Style A")
    _card(lib / "B", "style", ".safetensors", 2, "Style B")

    assert len(find_html_files(config, ["l"])) == 2
    assert sorted(c["name"] for c in _gallery_cards(tmp_path, config)) == ["Style A", "Style B"]


def test_card_finds_model_file_with_configured_extension(tmp_path):
    config, lib = _config(tmp_path, patterns=("*.safetensors", "*.gguf"))
    _card(lib / "unet", "flux-q8", ".gguf", 3, "Flux")

    (card,) = _gallery_cards(tmp_path, config)
    assert card["file_path"].endswith("unet/flux-q8.gguf")


def test_model_file_extensions_put_configured_patterns_first():
    config = {"input_paths": {"a": {"patterns": ["*.GGUF", "lora_*.safetensors"]}}}
    extensions = model_file_extensions(config)
    assert extensions[0] == ".gguf"
    assert ".safetensors" in extensions and extensions.count(".gguf") == 1
    assert ContextBuilder({"api": {}}).model_extensions[0] == ".safetensors"


def test_nested_input_paths_list_each_file_once(tmp_path):
    config, lib = _config(tmp_path)
    sub = lib / "Illustrious"
    sub.mkdir()
    (sub / "x.safetensors").write_bytes(b"x")
    config["input_paths"]["sub"] = {"path": str(sub), "type": "LORA",
                                    "patterns": ["*.safetensors"]}
    job = ScanJob(config, "scan", {"paths": ["l", "sub"], "recursive": True,
                                   "use_cached_metadata": True}, MagicMock())
    assert job.discover()
    assert [os.path.basename(f) for f in job.files] == ["x.safetensors"]


def test_gallery_data_leaves_out_python_only_fields(tmp_path):
    config, lib = _config(tmp_path)
    _card(lib / "A", "style", ".safetensors", 1, "Style A")
    (card,) = _gallery_cards(tmp_path, config)
    assert "model_id" not in card
    assert "local_version_count" not in card
    assert set(card["stats"]) == {"downloads", "rating"}


def test_version_index_is_built_once_under_parallel_access(tmp_path):
    import threading
    from unittest.mock import patch

    from civitscraper.html.context import VersionIndexCache

    (tmp_path / "a.json").write_text(json.dumps({"id": 1, "modelId": 2}))
    cache = VersionIndexCache()
    real_build = cache._build_index
    calls = []

    def slow_build(directory):
        calls.append(directory)
        threading.Event().wait(0.05)
        real_build(directory)

    with patch.object(cache, "_build_index", side_effect=slow_build):
        threads = [threading.Thread(target=cache.get_html_path, args=(str(tmp_path), 1))
                   for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert calls == [str(tmp_path)]
    assert cache.get_model_versions(str(tmp_path), 2, 1)


def test_images_folder_preview_must_belong_to_the_model(tmp_path):
    builder = ContextBuilder({"api": {}})
    images = tmp_path / "images"
    images.mkdir()
    (images / "foobar.png").write_bytes(b"x")
    (images / "foo.txt").write_bytes(b"x")
    card = str(tmp_path / "foo.html")
    assert builder._try_images_directory(card, str(tmp_path)) is None
    (images / "foo_2.webp").write_bytes(b"x")
    (images / "foo.1.png").write_bytes(b"x")
    found = builder._try_images_directory(card, str(tmp_path))
    assert found["path"].endswith("foo.1.png")  # sorted: deterministic pick

"""Regression tests: every reader of sidecars/previews honors configured output paths."""

import json
import os
from unittest.mock import MagicMock

import pytest

from civitscraper.html.context import ContextBuilder
from civitscraper.jobs.executor import JobExecutor
from civitscraper.organization.organizer import FileOrganizer
from civitscraper.scanner.discovery import (
    filter_files,
    find_html_files,
    get_image_path,
    get_metadata_path,
    get_model_type,
    has_metadata,
    is_within,
    list_preview_files,
)
from civitscraper.scanner.image_manager import ImageManager
from civitscraper.scanner.metadata_manager import MetadataManager


def make_config(tmp_path, base_dir=True, preview_template="{model_name}.preview{ext}"):
    models = tmp_path / "loras"
    models.mkdir(exist_ok=True)
    config = {
        "api": {"base_url": "https://example.invalid"},
        "input_paths": {
            "l": {"path": str(models), "type": "LORA", "patterns": ["*.safetensors"]},
        },
        "output": {
            "metadata": {"html": {"filename": "{model_name}.html"}},
            "images": {"max_count": 2, "filenames": {"preview": preview_template}},
        },
    }
    if base_dir:
        config["output"]["base_dir"] = str(tmp_path / "central")
    return config, models


def make_model(models, name="foo"):
    path = models / f"{name}.safetensors"
    path.write_bytes(b"x")
    return str(path)


def write_sidecar(config, model_path, data=None):
    meta = data or {"id": 1, "modelId": 2, "name": "v1", "images": []}
    MetadataManager(config, MagicMock()).save_metadata(model_path, dict(meta))
    return get_metadata_path(model_path, config)


@pytest.mark.parametrize("base_dir", [True, False])
def test_skip_existing_uses_configured_metadata_location(tmp_path, base_dir):
    config, models = make_config(tmp_path, base_dir=base_dir)
    model = make_model(models)
    sidecar = write_sidecar(config, model)

    assert os.path.isfile(sidecar)
    assert has_metadata(model, config)
    assert filter_files([model], skip_existing=True, config=config) == []


def test_custom_metadata_path_and_filename(tmp_path):
    config, models = make_config(tmp_path, base_dir=False)
    config["output"]["metadata"]["path"] = str(tmp_path / "meta")
    config["output"]["metadata"]["filename"] = "{model_name}.civitai.json"
    model = make_model(models)
    sidecar = write_sidecar(config, model)

    assert sidecar == str(tmp_path / "meta" / "foo.civitai.json")
    assert filter_files([model], skip_existing=True, config=config) == []


def test_cached_metadata_loads_from_base_dir(tmp_path):
    config, models = make_config(tmp_path)
    model = make_model(models)
    write_sidecar(config, model)
    executor = JobExecutor.__new__(JobExecutor)
    executor.config = config

    assert executor._has_cached_metadata(model, config)
    assert executor._load_cached_metadata(model, config)["id"] == 1


def test_gallery_card_built_for_base_dir_model(tmp_path):
    config, models = make_config(tmp_path)
    model = make_model(models)
    write_sidecar(config, model)
    preview = get_image_path(model, config, "preview1", ".jpeg")
    os.makedirs(os.path.dirname(preview), exist_ok=True)
    open(preview, "wb").close()

    card = ContextBuilder(config)._process_gallery_model(model, str(tmp_path / "g.html"))

    assert card is not None
    assert card["version_id"] == 1
    assert card["preview_image_path"] == os.path.abspath(preview)


def test_gallery_card_for_existing_base_dir_html_finds_preview(tmp_path):
    config, models = make_config(tmp_path)
    model = make_model(models)
    sidecar = write_sidecar(config, model)
    html = os.path.splitext(sidecar)[0] + ".html"
    open(html, "w").close()
    preview = get_image_path(model, config, "preview1", ".png")
    open(preview, "wb").close()

    assert html in find_html_files(config, ["l"])
    card = ContextBuilder(config)._process_gallery_model(html, str(tmp_path / "g.html"))
    assert card["preview_image_path"] == os.path.abspath(preview)


@pytest.mark.parametrize("name", ["char [v2]", "plain"])
@pytest.mark.parametrize(
    "template", ["{model_name}.preview{ext}", "previews_{model_name}_{image_type}{ext}"]
)
def test_list_preview_files_matches_template_and_glob_chars(tmp_path, name, template):
    config, models = make_config(tmp_path, preview_template=template)
    model = make_model(models, name)
    paths = [
        get_image_path(model, config, f"preview{i}", ext)
        for i, ext in [(2, ".mp4"), (1, ".jpeg"), (10, ".webp")]
    ]
    for p in paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").close()
    # Noise that must be ignored
    open(os.path.join(os.path.dirname(paths[0]), f"{name}.preview.jpeg"), "wb").close()
    open(os.path.join(os.path.dirname(paths[0]), "other.preview1.jpeg"), "wb").close()

    result = list_preview_files(model, config)

    assert [(i, v) for _, i, v in result] == [(1, False), (2, True), (10, False)]


def test_image_manager_counts_and_cleans_in_base_dir(tmp_path):
    config, models = make_config(tmp_path)
    model = make_model(models)
    paths = []
    for i in (1, 2, 3):
        p = get_image_path(model, config, f"preview{i}", ".jpeg")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").close()
        paths.append(p)
    manager = ImageManager(config, MagicMock())

    assert manager._count_existing_previews(model) == 3
    manager._clean_up_old_previews(model, max_count=2)
    assert [os.path.exists(p) for p in paths] == [True, True, False]


def test_skip_existing_images_not_redownloaded_in_base_dir(tmp_path):
    config, models = make_config(tmp_path)
    config["skip_existing"] = True
    model = make_model(models)
    for i in (1, 2):
        p = get_image_path(model, config, f"preview{i}", ".jpeg")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").close()
    api = MagicMock()
    metadata = {"images": [{"url": f"https://x/{i}.jpeg"} for i in range(3)]}

    result = ImageManager(config, api).download_images(model, metadata)

    api.download_image.assert_not_called()
    assert len(result) == 2


def test_model_type_uses_path_containment_not_prefix(tmp_path):
    config, models = make_config(tmp_path, base_dir=False)
    other = tmp_path / "loras2"
    other.mkdir()
    nested = models / "sdxl"
    nested.mkdir()
    config["input_paths"]["c"] = {"path": str(other), "type": "Checkpoint", "patterns": []}
    config["input_paths"]["n"] = {"path": str(nested), "type": "LORA-XL", "patterns": []}

    assert get_model_type(str(other / "a.safetensors"), config) == "Checkpoint"
    assert get_model_type(str(models / "a.safetensors"), config) == "LORA"
    # Most specific input path wins for nested roots
    assert get_model_type(str(nested / "a.safetensors"), config) == "LORA-XL"
    assert not is_within(str(other / "a"), str(models))


def test_sync_lora_triggers_reads_base_dir_sidecar(tmp_path):
    config, models = make_config(tmp_path)
    model = make_model(models)
    write_sidecar(config, model, {"id": 1, "trainedWords": ["alpha", "beta"], "images": []})
    loras_file = tmp_path / "loras.json"
    loras_file.write_text(json.dumps([{"id": "loras/foo.safetensors"}]))
    config["jobs"] = {
        "sync": {"type": "sync-lora-triggers", "paths": ["l"], "loras_file": str(loras_file)}
    }
    executor = JobExecutor.__new__(JobExecutor)
    executor.config = config

    assert executor.execute_job("sync")
    data = json.loads(loras_file.read_text())
    assert data[0]["metadata"]["lora_triggers"] == "alpha, beta"


def test_move_with_base_dir_keeps_central_sidecar_in_place(tmp_path):
    config, models = make_config(tmp_path)
    model = make_model(models)
    sidecar = write_sidecar(config, model)
    preview = get_image_path(model, config, "preview1", ".jpeg")
    open(preview, "wb").close()
    config["organization"] = {
        "enabled": True,
        "custom_template": "{model_type}",
        "output_dir": "{model_dir}/organized",
        "operation_mode": "move",
    }
    metadata = {"id": 1, "model": {"type": "LORA"}}

    target = FileOrganizer(config).organize_file(model, metadata)

    assert target and os.path.isfile(target) and not os.path.exists(model)
    # Organized model stays inside the LORA input root, so its central sidecar
    # location is unchanged and nothing may be moved to a mangled path.
    assert get_metadata_path(target, config) == sidecar
    assert os.path.isfile(sidecar)
    assert os.path.isfile(preview)


def test_move_default_layout_moves_related_files_with_model(tmp_path):
    config, models = make_config(tmp_path, base_dir=False)
    model = make_model(models)
    sidecar = write_sidecar(config, model)
    previews = []
    for i in (1, 12):
        p = get_image_path(model, config, f"preview{i}", ".jpeg")
        open(p, "wb").close()
        previews.append(p)
    config["organization"] = {
        "enabled": True,
        "custom_template": "{model_type}",
        "operation_mode": "move",
    }

    target = FileOrganizer(config).organize_file(model, {"model": {"type": "LORA"}})

    assert os.path.isfile(get_metadata_path(target, config))
    assert not os.path.exists(sidecar)
    # preview12 used to be left behind (range(10) lookup)
    assert [i for _, i, _ in list_preview_files(target, config)] == [1, 12]

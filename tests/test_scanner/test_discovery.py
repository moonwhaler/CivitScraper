"""Tests for output path resolution in civitscraper.scanner.discovery."""

import os

from civitscraper.scanner.discovery import get_html_path, get_image_path, get_metadata_path


def make_config(base_dir=None, model_type="LORA"):
    config = {
        "input_paths": {
            "my-models": {
                "path": "/models/loras",
                "type": model_type,
                "patterns": ["*.safetensors"],
            }
        },
        "output": {
            "metadata": {
                "filename": "{model_name}.json",
                "html": {"filename": "{model_name}.html"},
            },
            "images": {"filenames": {"preview": "{model_name}.preview{ext}"}},
        },
    }
    if base_dir is not None:
        config["output"]["base_dir"] = base_dir
    return config


MODEL_FILE = "/models/loras/my-model.safetensors"


def test_get_metadata_path_without_base_dir_uses_model_dir():
    config = make_config()
    path = get_metadata_path(MODEL_FILE, config)
    assert path == os.path.join("/models/loras", "my-model.json")


def test_get_metadata_path_with_base_dir_uses_base_dir_and_model_type():
    config = make_config(base_dir="/central/output")
    path = get_metadata_path(MODEL_FILE, config)
    assert path == os.path.join("/central/output", "LORA", "my-model.json")


def test_get_metadata_path_with_base_dir_expands_home(monkeypatch):
    monkeypatch.setenv("HOME", "/home/testuser")
    config = make_config(base_dir="~/civitai-data")
    path = get_metadata_path(MODEL_FILE, config)
    assert path == os.path.join("/home/testuser/civitai-data", "LORA", "my-model.json")


def test_get_html_path_without_base_dir_uses_model_dir():
    config = make_config()
    path = get_html_path(MODEL_FILE, config)
    assert path == os.path.join("/models/loras", "my-model.html")


def test_get_html_path_with_base_dir_uses_base_dir_and_model_type():
    config = make_config(base_dir="/central/output")
    path = get_html_path(MODEL_FILE, config)
    assert path == os.path.join("/central/output", "LORA", "my-model.html")


def test_get_image_path_without_base_dir_uses_model_dir():
    config = make_config()
    path = get_image_path(MODEL_FILE, config, image_type="preview", ext=".jpg")
    assert path == os.path.join("/models/loras", "my-model.preview.jpg")


def test_get_image_path_with_base_dir_uses_base_dir_and_model_type():
    config = make_config(base_dir="/central/output")
    path = get_image_path(MODEL_FILE, config, image_type="preview", ext=".jpg")
    assert path == os.path.join("/central/output", "LORA", "my-model.preview.jpg")


def test_get_image_path_with_base_dir_preserves_index_number():
    config = make_config(base_dir="/central/output")
    path = get_image_path(MODEL_FILE, config, image_type="preview1", ext=".jpg")
    assert path == os.path.join("/central/output", "LORA", "my-model.preview1.jpg")

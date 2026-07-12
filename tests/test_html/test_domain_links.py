"""Tests that model-page links route to civitai.red for NSFW models."""

from civitscraper.html.context import ContextBuilder

_CB_CONFIG = {
    "api": {},
    "output": {
        "metadata": {
            "path": "{model_dir}",
            "filename": "{model_name}.json",
            "html": {"filename": "{model_name}.html"},
        }
    },
}


def make_builder():
    return ContextBuilder(_CB_CONFIG)


def test_model_url_nsfw_routes_to_red(tmp_path):
    builder = make_builder()
    model_file = tmp_path / "m.safetensors"
    model_file.write_text("x")
    metadata = {
        "id": 456,
        "modelId": 123,
        "nsfwLevel": 60,
        "images": [],
        "model": {"name": "N", "type": "LORA"},
    }
    ctx = builder.build_model_context(str(model_file), metadata)
    assert ctx["model_url"] == "https://civitai.red/models/123?modelVersionId=456"


def test_model_url_sfw_routes_to_com(tmp_path):
    builder = make_builder()
    model_file = tmp_path / "m.safetensors"
    model_file.write_text("x")
    metadata = {
        "id": 456,
        "modelId": 123,
        "nsfwLevel": 1,
        "images": [],
        "model": {"name": "N", "type": "LORA"},
    }
    ctx = builder.build_model_context(str(model_file), metadata)
    assert ctx["model_url"] == "https://civitai.com/models/123?modelVersionId=456"

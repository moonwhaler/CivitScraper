"""Page templates: filters, inlined assets, model page context and gallery assets."""

import json
import os
import re

import pytest
from jinja2 import Undefined

from civitscraper.html.context import ContextBuilder
from civitscraper.html.filters import compact, date, filesize, type_slug, version_label
from civitscraper.html.generator import HTMLGenerator
from civitscraper.html.images import generation_params
from civitscraper.html.renderer import TemplateRenderer

# --- filters ---------------------------------------------------------------------


def test_filters_format_and_tolerate_missing_values():
    """Filters format values and return "" for anything missing."""
    assert filesize(89702.4) == "87.6 MB"
    assert filesize(512) == "512 KB"
    assert filesize(6_500_000) == "6.2 GB"
    assert compact(950) == "950"
    assert compact(12_345) == "12.3k"
    assert compact(4_000_000) == "4M"
    assert date("2026-02-15T07:01:02.000Z") == "2026-02-15"
    assert type_slug("LORA") == "lora"
    assert type_slug("TextualInversion") == "embedding"
    assert type_slug("LoCon") == "locon"
    assert type_slug("Wildcards") == "other"
    assert version_label("1.0") == "v1.0"
    assert version_label("v2.0") == "v2.0"
    assert version_label("224_ncKR2_a0700") == "224_ncKR2_a0700"
    for empty in (None, "", Undefined()):
        assert filesize(empty) == ""
        assert compact(empty) == ""
        assert date(empty) == ""
        assert type_slug(empty) == "other"
        assert version_label(empty) == ""


def test_generation_params_follow_infotext_order():
    """Settings come out in A1111 order; nested values and the prompt are left out."""
    meta = {
        "seed": 42,
        "cfgScale": 7,
        "steps": 30,
        "sampler": "Euler a",
        "width": 832,
        "height": 1216,
        "Model hash": "abc123",
        "scheduler": "karras",
        "clipSkip": 2,
        "resources": [{"name": "x"}],
        "prompt": "not a param",
    }
    assert generation_params(meta) == [
        ["Steps", "30"],
        ["Sampler", "Euler a"],
        ["Schedule type", "karras"],
        ["CFG scale", "7"],
        ["Seed", "42"],
        ["Size", "832x1216"],
        ["Model hash", "abc123"],
        ["Clip skip", "2"],
    ]
    assert generation_params({}) == []


# --- model page ------------------------------------------------------------------


def _sidecar(**overrides):
    data = {
        "id": 200,
        "modelId": 20,
        "name": "v2.0",
        "baseModel": "Illustrious",
        "createdAt": "2026-01-02T00:00:00.000Z",
        "trainedWords": ["foo style", "bar"],
        "description": "<p>Use it.</p>",
        "stats": {"downloadCount": 12345, "thumbsUpCount": 10},
        "model": {"name": "Foo Style", "type": "LORA"},
        "parentModel": {"id": 20, "name": "Foo Style", "creator": {"username": "alice"}},
        "files": [
            {
                "name": "foo.safetensors",
                "sizeKB": 89702.4,
                "primary": True,
                "hashes": {"AutoV2": "E382D81D62", "SHA256": "E382D81D62" + "0" * 54},
                "metadata": {"format": "SafeTensor", "fp": "fp16"},
            }
        ],
        "images": [
            {
                "url": "https://img.example/1.jpeg",
                "width": 832,
                "height": 1216,
                "nsfwLevel": 1,
                "meta": {
                    "prompt": "a cat</script><script>alert(1)</script>",
                    "negativePrompt": "blurry",
                    "steps": 20,
                    "width": 832,
                    "height": 1216,
                },
            }
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def model_page(tmp_path, sample_config):
    """Render the detail page of a model with a sidecar and one preview."""
    folder = tmp_path / "loras #1"
    folder.mkdir()
    model = folder / "foo.safetensors"
    model.write_bytes(b"x")
    (folder / "foo.json").write_text(json.dumps(_sidecar()))
    (folder / "foo.preview1.jpeg").write_bytes(b"jpeg")
    sample_config["output"]["metadata"]["html"]["gallery_path"] = str(tmp_path / "gallery.html")
    context = ContextBuilder(sample_config).build_model_context(str(model), _sidecar())
    html = TemplateRenderer().render_model(context)
    return context, html


def test_model_context_has_creator_hashes_and_portable_paths(model_page):
    """Creator falls back to parentModel; paths are relative to the page."""
    context, _ = model_page
    assert context["creator"] == "alice"  # from parentModel
    assert context["hashes"]["AutoV2"] == "E382D81D62"
    assert context["file_rel_path"] == "foo.safetensors"
    assert context["gallery_path"] == "../gallery.html"
    image = context["images"][0]
    assert image["width"] == 832 and image["height"] == 1216
    assert image["nsfw"] is False
    assert ["Size", "832x1216"] in image["params"]


def test_model_page_inlines_assets_unescaped(model_page):
    """
    Inline CSS/JS byte for byte.

    Autoescaping would turn quotes and '>' into entities, which browsers do not
    decode inside <style>/<script>.
    """
    _, html = model_page
    templates = TemplateRenderer().template_dir
    for asset in ("css/theme.css", "css/model.css", "js/common.js", "js/model.js"):
        with open(os.path.join(templates, asset), encoding="utf-8") as f:
            source = f.read()
        assert source in html, asset
        assert "</script" not in source and "</style" not in source


def test_model_page_image_data_is_safe_json(model_page):
    """Image data parses as JSON and a prompt cannot close the script element."""
    _, html = model_page
    match = re.search(
        r'<script type="application/json" id="images-data">(.*?)</script>', html, re.S
    )
    assert match, "image data block missing"
    images = json.loads(match.group(1))
    assert images[0]["prompt"] == "a cat</script><script>alert(1)</script>"
    assert "<script>alert(1)" not in html
    assert "Unknown" not in re.sub(r"<script.*?</script>", "", html, flags=re.S)


def test_model_page_shows_file_facts(model_page):
    """Creator, file size and download count are shown formatted."""
    _, html = model_page
    assert 'src="foo.preview1.jpeg"' in html
    assert "alice" in html and "87.6 MB" in html and "12.3k" in html


def test_model_page_encodes_local_media_urls():
    """A '#' or space in a folder name must not cut the media URL short."""
    html = TemplateRenderer().render_model(
        {
            "model_name": "m",
            "model_type": "LORA",
            "images": [{"path": "../a #1/x y.jpeg", "params": []}],
            "metadata": {},
            "gallery_path": "../g #2/gallery.html",
        }
    )
    assert 'src="../a%20%231/x%20y.jpeg"' in html
    assert 'href="../g%20%232/gallery.html"' in html


# --- gallery ---------------------------------------------------------------------


def test_gallery_ships_new_assets(tmp_path, sample_config):
    """The gallery copies and links the theme, shared JS and its own assets."""
    model = tmp_path / "foo.safetensors"
    model.write_bytes(b"x")
    (tmp_path / "foo.json").write_text(json.dumps(_sidecar()))
    out = tmp_path / "out" / "gallery.html"
    HTMLGenerator(sample_config).generate_gallery([str(model)], str(out), include_existing=False)

    html = out.read_text()
    for asset in ("css/theme.css", "css/gallery.css", "js/common.js", "js/gallery.js"):
        assert f'"{asset}"' in html
        assert os.path.isfile(out.parent / asset)
    assert "base.css" not in html
    assert (
        html.index("js/common.js") < html.index("data/models_data.js") < html.index("js/gallery.js")
    )


def test_detail_page_trigger_words_are_cleaned(tmp_path, sample_config):
    """Trailing commas and blanks are dropped; a single string stays one word."""
    model = tmp_path / "foo.safetensors"
    model.write_bytes(b"x")
    builder = ContextBuilder(sample_config)
    context = builder.build_model_context(
        str(model), _sidecar(trainedWords=["foo style,", " ", "bar ,"])
    )
    assert context["trigger_words"] == ["foo style", "bar"]
    html = TemplateRenderer().render_model(context)
    assert 'data-copy-text="foo style, bar"' in html
    single = builder.build_model_context(str(model), _sidecar(trainedWords="one phrase"))
    assert single["trigger_words"] == ["one phrase"]


def test_image_data_holds_only_what_the_page_reads(model_page):
    """Settings travel in params; the old per-setting keys are gone."""
    context, _ = model_page
    assert set(context["images"][0]) == {
        "path", "prompt", "negative_prompt", "params", "width", "height", "nsfw", "is_video",
        "archived",
    }


def test_inlined_assets_are_read_once_per_renderer(monkeypatch):
    """Rendering many pages does not re-read theme.css, model.css and the scripts."""
    import builtins

    renderer = TemplateRenderer()
    opened = []
    real_open = builtins.open

    def counting_open(path, *args, **kwargs):
        opened.append(os.path.basename(str(path)))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    first = renderer._read_file("css/theme.css")
    assert renderer._read_file("css/theme.css") is first
    assert opened.count("theme.css") == 1

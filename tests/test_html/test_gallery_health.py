"""Gallery card data: search fields, health flags, duplicates and portable paths."""

import json
import os
import re
from unittest.mock import MagicMock

import pytest

from civitscraper.html import gallery_data
from civitscraper.html.context import (
    HEALTH_DUPLICATE,
    HEALTH_NO_PREVIEW,
    HEALTH_UPDATE,
    ContextBuilder,
    card_trigger_words,
    update_available,
)
from civitscraper.html.gallery_data import collapse_candidates, portable_path
from civitscraper.html.generator import HTMLGenerator
from civitscraper.jobs.executor import JobExecutor


def _card(**kwargs):
    card = {
        "name": "Model",
        "model_id": 1,
        "version_id": 100,
        "version": "v1",
        "base_model": "SD 1.5",
        "created_at": "2024-01-01T00:00:00",
        "preview_image_path": "/img/a.png",
        "html_path": "/out/a.html",
        "file_path": "/models/a.safetensors",
        "sibling_versions": [],
    }
    card.update(kwargs)
    return card


def _remote(version_id, created, base):
    return {"id": version_id, "name": f"r{version_id}", "createdAt": created, "baseModel": base}


# --- card fields ---------------------------------------------------------------


def test_card_trigger_words_are_capped():
    """At most 10 entries / 300 characters; blanks and trailing commas dropped."""
    assert card_trigger_words(["a", "", None, " b ", "c,"]) == ["a", "b", "c"]
    assert card_trigger_words("solo") == ["solo"]
    assert len(card_trigger_words([f"w{i}" for i in range(30)])) == 10
    assert card_trigger_words(["x" * 200, "y" * 200, "z"]) == ["x" * 200]
    assert card_trigger_words(None) == []


def test_card_has_creator_tags_triggers_and_model_path(tmp_path):
    """Search and copy fields come from the sidecar; parentModel wins over model."""
    model = tmp_path / "foo.safetensors"
    model.write_bytes(b"x")
    (tmp_path / "foo.json").write_text(
        json.dumps(
            {
                "id": 1,
                "modelId": 2,
                "name": "v1",
                "trainedWords": ["trig"],
                "model": {"name": "Foo", "type": "LORA", "tags": ["old"]},
                "parentModel": {"creator": {"username": "alice"}, "tags": ["style", "anime"]},
            }
        )
    )
    config = {"input_paths": {"l": {"path": str(tmp_path), "type": "LORA"}}}

    card = ContextBuilder(config)._process_gallery_model(str(model), str(tmp_path / "g.html"))

    assert card["creator"] == "alice"
    assert card["tags"] == ["style", "anime"]
    assert card["trigger_words"] == ["trig"]
    assert card["file_path"] == str(model)


# --- update available ------------------------------------------------------------


def test_update_flag_for_newer_remote_on_same_base_model():
    """A newer remote version on a base model the user has is an update."""
    cards = [_card(sibling_versions=[_remote(101, "2024-06-01", "SD 1.5")])]

    merged = ContextBuilder.merge_gallery_models(cards)[0]

    assert HEALTH_UPDATE in merged["health"]
    assert merged["update_version"] == "r101"
    assert {v["base_model"] for v in merged["versions"]} == {"SD 1.5"}


def test_no_update_flag_for_newer_version_on_other_base_model():
    """A new SDXL release does not nag someone who only has the SD 1.5 version."""
    cards = [_card(sibling_versions=[_remote(101, "2024-06-01", "SDXL 1.0")])]

    assert HEALTH_UPDATE not in ContextBuilder.merge_gallery_models(cards)[0]["health"]


def test_update_compared_per_local_base_model():
    """With SD 1.5 and SDXL local, a newer SDXL release still counts."""
    versions = [
        {"is_local": True, "base_model": "SD 1.5", "created_at": "2024-05-01"},
        {"is_local": True, "base_model": "SDXL", "created_at": "2024-01-01"},
        {"is_local": False, "base_model": "SDXL", "created_at": "2024-03-01", "name": "x2"},
        {"is_local": False, "base_model": "SD 1.5", "created_at": "2024-04-01", "name": "old"},
    ]

    assert update_available(versions)["name"] == "x2"


def test_older_remote_versions_are_not_updates():
    """Only versions newer than the local one count."""
    cards = [_card(sibling_versions=[_remote(99, "2023-01-01", "SD 1.5")])]

    assert ContextBuilder.merge_gallery_models(cards)[0]["health"] == []


# --- preview / duplicates ----------------------------------------------------------


def test_missing_preview_flag():
    """A card without a preview image is flagged."""
    merged = ContextBuilder.merge_gallery_models([_card(preview_image_path=None)])[0]

    assert merged["health"] == [HEALTH_NO_PREVIEW]


def test_same_version_with_different_filenames_is_duplicate():
    """Two files of one version (e.g. a renamed copy) merge and are flagged."""
    cards = [
        _card(file_path="/models/a.safetensors", html_path="/models/a.html"),
        _card(file_path="/other/a-copy.safetensors", html_path="/other/a-copy.html"),
    ]

    merged = ContextBuilder.merge_gallery_models(cards)

    assert len(merged) == 1
    assert HEALTH_DUPLICATE in merged[0]["health"]
    assert sorted(merged[0]["duplicates"]) == [
        "/models/a.safetensors",
        "/other/a-copy.safetensors",
    ]
    assert len(merged[0]["versions"]) == 1


def _builder(tmp_path, mode="copy"):
    config = {
        "input_paths": {"l": {"path": str(tmp_path / "loras"), "type": "LORA"}},
        "organization": {"enabled": True, "operation_mode": mode},
    }
    return ContextBuilder(config)


def _model(directory, name, version_id):
    directory.mkdir(parents=True, exist_ok=True)
    model = directory / f"{name}.safetensors"
    model.write_bytes(name.encode())
    (directory / f"{name}.json").write_text(json.dumps({"id": version_id, "modelId": 1}))
    (directory / f"{name}.html").write_text("")
    return model


def test_same_filename_same_version_in_two_folders_is_duplicate(tmp_path):
    """The same version under one name in two real folders becomes one card + duplicates."""
    a = _model(tmp_path / "loras" / "a", "foo", 7)
    b = _model(tmp_path / "loras" / "b", "foo", 7)

    result = collapse_candidates([str(a), str(b)], _builder(tmp_path))

    assert len(result) == 1
    assert sorted(result[0][1]) == sorted([str(a), str(b)])


def test_same_filename_different_versions_get_their_own_cards(tmp_path):
    """Different versions that share a filename are no longer collapsed into one card."""
    a = _model(tmp_path / "loras" / "a", "foo", 7)
    b = _model(tmp_path / "loras" / "b", "foo", 8)

    result = collapse_candidates([str(a), str(b)], _builder(tmp_path))

    assert sorted(path for path, _ in result) == sorted([str(a), str(b)])
    assert all(dups == [] for _, dups in result)


@pytest.mark.parametrize("mode", ["copy", "symlink"])
def test_organized_mirror_is_not_a_duplicate(tmp_path, mode):
    """A copy-mode original and its organized copy are one card, not duplicates."""
    original = _model(tmp_path / "loras", "foo", 7)
    mirror = _model(tmp_path / "loras" / "organized" / "LORA", "foo", 7)
    html = tmp_path / "loras" / "organized" / "LORA" / "foo.html"

    result = collapse_candidates([str(original), str(html)], _builder(tmp_path, mode))

    assert result == [(str(html), [])]
    assert mirror.exists()


def test_model_file_and_its_card_are_one_entry(tmp_path):
    """A new model file and its freshly written HTML card collapse silently."""
    model = _model(tmp_path / "loras", "foo", 7)

    result = collapse_candidates(
        [str(model), str(tmp_path / "loras" / "foo.html")], _builder(tmp_path)
    )

    assert len(result) == 1 and result[0][1] == []


# --- portable paths ----------------------------------------------------------------


def test_portable_path_is_relative_with_forward_slashes(tmp_path):
    """Local paths become relative to the gallery; URLs stay as they are."""
    gallery_dir = str(tmp_path / "html")
    target = str(tmp_path / "loras" / "a #1.png")

    assert portable_path(target, gallery_dir) == "../loras/a #1.png"
    assert portable_path(target, gallery_dir, portable=False) == target
    assert portable_path("https://x.invalid/a.png", gallery_dir) == "https://x.invalid/a.png"
    assert portable_path(None, gallery_dir) is None


def test_portable_path_other_drive_stays_absolute(tmp_path, monkeypatch):
    """When no relative path exists (Windows, other drive) the absolute path is kept."""

    def no_relpath(path, start):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(gallery_data.os.path, "relpath", no_relpath)
    target = str(tmp_path / "a.png")

    assert portable_path(target, str(tmp_path / "html")) == target


# --- end to end --------------------------------------------------------------------


def _gallery_data(gallery_dir):
    with open(os.path.join(gallery_dir, "data", "models_data.js"), encoding="utf-8") as f:
        text = f.read()
    cards = json.loads(re.search(r"window\.allModelsData = (.*);\n", text).group(1))
    unmatched = json.loads(re.search(r"window\.galleryUnmatched = (.*);$", text).group(1))
    return cards, unmatched


def test_gallery_paths_resolve_after_moving_the_tree(tmp_path, monkeypatch):
    """Card links are relative, so they still resolve once gallery + models move together."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "lib"
    model = _model(root / "loras", "foo #1", 7)
    (root / "loras" / "foo #1.preview1.jpeg").write_bytes(b"i")
    config = {
        "input_paths": {"l": {"path": str(root / "loras"), "type": "LORA"}},
        "output": {"images": {"max_count": 1}},
    }
    HTMLGenerator(config).generate_gallery(
        [str(model)], str(root / "html" / "gallery.html"), include_existing=False
    )

    moved = tmp_path / "elsewhere"
    os.rename(root, moved)
    cards, _ = _gallery_data(str(moved / "html"))

    card = cards[0]
    for key in ("html_path", "preview_image_path", "file_path"):
        assert not os.path.isabs(card[key])
        assert os.path.exists(os.path.join(moved, "html", card[key])), key


def test_unmatched_files_are_listed_with_reason(tmp_path, monkeypatch):
    """Files without a sidecar are listed; 'not on CivitAI' only for a cached 404."""
    monkeypatch.chdir(tmp_path)
    models = tmp_path / "loras"
    models.mkdir()
    for name in ("known", "missing", "flaky"):
        (models / f"{name}.safetensors").write_bytes(name.encode())
    from civitscraper.api.exceptions import ClientError, ServerError

    def by_hash(h, force_refresh=False):
        import hashlib

        if h == hashlib.sha256(b"missing").hexdigest().upper():
            raise ClientError(404, "not found")
        if h == hashlib.sha256(b"flaky").hexdigest().upper():
            raise ServerError(503, "down")
        return {
            "id": 1,
            "modelId": 2,
            "name": "v",
            "model": {"name": "K", "type": "LORA"},
            "images": [{"url": "https://x.invalid/a.jpeg"}],
        }

    api = MagicMock()
    api.get_model_version_by_hash.side_effect = by_hash
    api.get_parent_model_with_versions.return_value = None
    api.download_image.return_value = (False, None)
    config = {
        "api": {"base_url": "https://x.invalid"},
        "input_paths": {"l": {"path": str(models), "type": "LORA", "patterns": ["*.safetensors"]}},
        "jobs": {
            "scan": {
                "type": "scan-paths",
                "paths": ["l"],
                "output": {
                    "metadata": {
                        "html": {"generate_gallery": True, "gallery_path": str(tmp_path / "g.html")}
                    },
                    "images": {"save": False},
                },
            }
        },
    }

    assert JobExecutor(config, api).execute_job("scan")

    _, unmatched = _gallery_data(str(tmp_path))
    assert [(u["name"], u["reason"]) for u in unmatched] == [
        ("flaky.safetensors", "no_metadata"),
        ("missing.safetensors", "not_on_civitai"),
    ]
    assert unmatched[0]["file_path"] == "loras/flaky.safetensors"

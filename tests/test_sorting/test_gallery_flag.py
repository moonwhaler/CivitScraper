"""The gallery's "misplaced" health flag."""

import os

from civitscraper.html.context import HEALTH_MISPLACED, ContextBuilder
from civitscraper.sorting.analysis import analyze, gallery_flags
from civitscraper.sorting.decisions import KEEP, Decisions, decisions_path, file_key

from .conftest import beta_lora, sidecar, write_safetensors


def key(path):
    return os.path.normcase(os.path.abspath(path))


def test_flags_point_to_the_right_folder(library):
    config, models = library
    p = write_safetensors(models / "Lora" / "Alpha" / "style" / "wrong.safetensors", beta_lora(9))
    sidecar(p, "Beta", version_id=999)
    flags = gallery_flags(config, ["lora", "unet", "vae"])
    assert flags == {key(p): {"to": "Lora/Beta/style", "why": "CivitAI says Beta"}}


def test_kept_files_are_not_flagged(library):
    config, models = library
    p = write_safetensors(models / "Lora" / "Alpha" / "style" / "wrong.safetensors", beta_lora(9))
    sidecar(p, "Beta", version_id=999)
    analysis = analyze(config, ["lora"])
    item = next(s.verdict.item for s in analysis.suggestions if s.path == p)
    decisions = Decisions(decisions_path(config))
    decisions.remember(file_key(item, config), KEEP, "wrong.safetensors")
    decisions.save()
    assert gallery_flags(config, ["lora", "unet", "vae"]) == {}


def test_merged_card_gets_the_health_flag():
    card = {
        "model_id": 1,
        "version_id": 2,
        "name": "x",
        "html_path": "/a.html",
        "file_path": "/a.safetensors",
        "misplaced": {"to": "Lora/Beta", "why": "CivitAI: Beta"},
        "preview_image_path": "/a.jpeg",
        "sibling_versions": [],
    }
    (merged,) = ContextBuilder.merge_gallery_models([card])
    assert HEALTH_MISPLACED in merged["health"]

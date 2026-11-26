"""Classifier verdicts and the learned folder layout."""

import os

from civitscraper.sorting.analysis import analyze
from civitscraper.sorting.classifier import CONFLICT, INFERRED, LABELLED, UNKNOWN
from civitscraper.sorting.layout import (
    MISPLACED,
    OK,
    STATE_BROKEN,
    STATE_CONFLICT,
    STATE_UNKNOWN,
    UNSORTED,
    WRONG_ROOT,
)

from .conftest import alpha_lora, beta_lora, checkpoint, delta_lora, sidecar, write_safetensors

PATHS = ["lora", "unet", "vae"]


def by_name(analysis):
    return {os.path.basename(s.path): s for s in analysis.suggestions}


def test_clean_library_is_all_ok(library):
    config, _ = library
    analysis = analyze(config, PATHS)
    assert {s.state for s in analysis.suggestions} == {OK}
    lora = next(r for r in analysis.roots if r.path_id == "lora")
    assert analysis.layout.folder_base[lora] == {"Alpha": "Alpha", "Beta": "Beta"}


def test_misplaced_labelled_file_keeps_its_category(library):
    config, models = library
    (models / "Lora" / "Beta" / "Style").mkdir()
    p = write_safetensors(models / "Lora" / "Alpha" / "style" / "wrong.safetensors", beta_lora(9))
    sidecar(p, "Beta", version_id=999)
    s = by_name(analyze(config, PATHS))["wrong.safetensors"]
    assert s.state == MISPLACED and s.verdict.status == LABELLED
    # existing "Style" is reused case-insensitively
    assert s.options[0].target == str(models / "Lora" / "Beta" / "Style" / "wrong.safetensors")
    assert s.confident


def test_unlabelled_file_is_inferred_from_structure(library):
    config, models = library
    write_safetensors(models / "Lora" / "Alpha" / "style" / "custom.safetensors", beta_lora(7))
    s = by_name(analyze(config, PATHS))["custom.safetensors"]
    assert s.verdict.status == INFERRED and s.verdict.base == "Beta"
    assert s.state == MISPLACED
    assert s.options[0].target_dir == str(models / "Lora" / "Beta" / "style")


def test_unlabelled_file_in_its_folder_stays(library):
    config, models = library
    write_safetensors(models / "Lora" / "Alpha" / "style" / "mine.safetensors", alpha_lora(8))
    assert by_name(analyze(config, PATHS))["mine.safetensors"].state == OK


def test_conflict_when_civitai_and_structure_disagree(library):
    config, models = library
    p = write_safetensors(models / "Lora" / "Beta" / "concept" / "liar.safetensors", alpha_lora(9))
    sidecar(p, "Beta", version_id=998)
    s = by_name(analyze(config, PATHS))["liar.safetensors"]
    assert s.verdict.status == CONFLICT and s.verdict.file_base == "Alpha"
    assert s.state == STATE_CONFLICT
    assert [o.key for o in s.options] == ["file"]  # CivitAI's reading: already in place
    assert not s.confident


def test_structural_twins_are_never_a_conflict(library):
    config, models = library
    # "Gamma" is labelled on CivitAI but built exactly like Beta.
    p = write_safetensors(models / "Lora" / "Beta" / "concept" / "twin.safetensors", beta_lora(1))
    sidecar(p, "Gamma", version_id=997)
    s = by_name(analyze(config, PATHS))["twin.safetensors"]
    assert s.verdict.status == LABELLED
    assert s.verdict.structural_family == {"Beta", "Gamma"}
    # Gamma has no folder: asked with a new folder, never moved by --yes
    assert s.state == MISPLACED and s.options[0].new_folder and not s.confident


def test_unknown_architecture_is_asked_only_when_unsorted(library):
    config, models = library
    write_safetensors(models / "Lora" / "Alpha" / "style" / "odd.safetensors", delta_lora())
    write_safetensors(models / "Lora" / "odd2.safetensors", delta_lora())
    result = by_name(analyze(config, PATHS))
    assert result["odd.safetensors"].verdict.status == UNKNOWN
    assert result["odd.safetensors"].state == OK
    assert result["odd2.safetensors"].state in (OK, STATE_UNKNOWN)
    assert not result["odd2.safetensors"].options


def test_inbox_folder_is_unsorted(library):
    config, models = library
    p = write_safetensors(models / "Lora" / "pre-sort" / "new.safetensors", alpha_lora(5))
    sidecar(p, "Alpha", version_id=996)
    s = by_name(analyze(config, PATHS))["new.safetensors"]
    assert s.state == UNSORTED
    assert s.options[0].target == str(models / "Lora" / "Alpha" / "new.safetensors")


def test_checkpoint_in_lora_folder_moves_to_unet(library):
    config, models = library
    p = write_safetensors(models / "Lora" / "Alpha" / "style" / "full.safetensors", checkpoint())
    sidecar(p, "Alpha", "Checkpoint", version_id=995)
    s = by_name(analyze(config, PATHS))["full.safetensors"]
    assert s.state == WRONG_ROOT
    assert s.options[0].target == str(models / "unet" / "alpha" / "full.safetensors")
    assert s.options[0].cross_root and not s.confident


def test_cross_root_proposes_the_folder_name_used_elsewhere(library):
    config, models = library
    p = write_safetensors(models / "Lora" / "Beta" / "concept" / "bck.safetensors",
                          checkpoint(3072))
    sidecar(p, "Beta", "Checkpoint", version_id=994)
    s = by_name(analyze(config, PATHS))["bck.safetensors"]
    assert s.options[0].target == str(models / "unet" / "Beta" / "bck.safetensors")
    assert s.options[0].new_folder


def test_override_maps_base_to_folder(library):
    config, models = library
    config["sorting"]["base_folders"] = {"Gamma": "Beta"}
    p = write_safetensors(models / "Lora" / "Beta" / "concept" / "twin.safetensors", beta_lora(1))
    sidecar(p, "Gamma", version_id=993)
    assert by_name(analyze(config, PATHS))["twin.safetensors"].state == OK


def test_small_folder_is_not_mapped(library):
    config, models = library
    for n in range(2):
        p = write_safetensors(models / "Lora" / "Misc" / f"m{n}.safetensors", alpha_lora(n + 20))
        sidecar(p, "Alpha", version_id=900 + n)
    analysis = analyze(config, PATHS)
    lora = next(r for r in analysis.roots if r.path_id == "lora")
    assert "Misc" not in analysis.layout.folder_base[lora]
    assert by_name(analysis)["m0.safetensors"].state == UNSORTED


def test_broken_file_is_reported(library):
    config, models = library
    (models / "Lora" / "Alpha" / "style" / "empty.safetensors").write_bytes(b"")
    s = by_name(analyze(config, PATHS))["empty.safetensors"]
    assert s.state == STATE_BROKEN and not s.options


def test_vae_root_is_report_only(library):
    config, models = library
    s = by_name(analyze(config, PATHS))["ae.safetensors"]
    assert s.state == OK and s.root.report_only


def test_generic_override_does_not_sort_a_flat_root(library):
    config, models = library
    config["sorting"]["base_folders"] = {"Alpha": "Alpha"}
    p = write_safetensors(models / "unet" / "flat.safetensors", checkpoint())
    sidecar(p, "Alpha", "Checkpoint", version_id=992)
    analysis = analyze(config, PATHS)
    unet = next(r for r in analysis.roots if r.path_id == "unet")
    # unet/alpha exists and maps; nothing invented
    assert analysis.layout.folder_base[unet] == {"alpha": "Alpha"}
    vae = next(r for r in analysis.roots if r.path_id == "vae")
    assert analysis.layout.folder_base[vae] == {}

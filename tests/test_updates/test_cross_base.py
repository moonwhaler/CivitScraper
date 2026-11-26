"""Versions for other base models you use: offered, placed in that base's folder, kept apart."""

import hashlib
import json
import os

import pytest

from civitscraper.updates import downloader as dl
from civitscraper.updates import job as job_module
from civitscraper.updates.job import UpdateJob
from test_sorting.conftest import alpha_lora, checkpoint, write_safetensors

from .conftest import FakeClient, FakeSession, blob, file_entry, sibling


def write_lora(path, vid, mid, base, siblings=(), created="2026-01-01"):
    write_safetensors(path, alpha_lora(vid % 7))
    with open(path, "rb") as f:
        content = f.read()
    meta = {"id": vid, "modelId": mid, "name": f"v{vid}", "baseModel": base, "createdAt": created,
            "model": {"name": f"Model {mid}", "type": "LORA", "nsfw": False},
            "files": [file_entry(vid, os.path.basename(path), content)],
            "siblingVersions": list(siblings) or [sibling(vid, created, base)]}
    with open(os.path.splitext(path)[0] + ".json", "w") as f:
        json.dump(meta, f)
    return content


@pytest.fixture
def cross(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    lora = tmp_path / "models" / "Lora"
    unet = tmp_path / "models" / "unet"
    unet.mkdir(parents=True)
    # Folders the layout learns: MOSS/ and krea2/ (3 labelled files each); no Pony folder.
    for i in range(3):
        write_lora(str(lora / "MOSS" / "misc" / f"m{i}.safetensors"), 600 + i, 700 + i, "MOSS Image")
        write_lora(str(lora / "krea2" / "misc" / f"k{i}.safetensors"), 610 + i, 710 + i, "Krea 2")
    # Model 500 "Chair": you have the MOSS version; CivitAI also has Krea 2 (two) and Pony.
    sibs = [sibling(51, "2026-03-01", "MOSS Image"), sibling(52, "2025-11-01", "Krea 2"),
            sibling(53, "2025-12-01", "Krea 2"), sibling(54, "2026-04-01", "Pony")]
    write_lora(str(lora / "MOSS" / "style" / "chair.safetensors"), 51, 500, "MOSS Image", sibs,
               "2026-03-01")
    contents = {52: blob(52), 53: blob(53), 54: blob(54)}
    versions = {v: {"id": v, "name": f"v{v}", "trainedWords": ["chair"],
                    "files": [file_entry(v, f"chair_{v}.safetensors", c)]}
                for v, c in contents.items()}
    files = {v * 10: c for v, c in contents.items()}
    config = {
        "api": {"base_url": "https://civitai.com/api/v1", "key": "KEY", "max_retries": 1,
                "batch": {"retry_delay": 0}},
        "input_paths": {
            "lora": {"path": str(lora), "type": "LORA", "patterns": ["*.safetensors"]},
            "unet": {"path": str(unet), "type": "Checkpoint", "patterns": ["*.safetensors"]},
        },
        "jobs": {"fetch-all": {"type": "scan-paths"},
                 "updates": {"type": "download-updates", "paths": ["lora", "unet"]}},
        "scanner": {"cache_dir": str(tmp_path / "cache")},
        "updates": {"min_free_gb": 0},
        "sorting": {"krita": {"enabled": False}},
        "_config_dir": str(tmp_path),
    }
    return config, tmp_path / "models", FakeClient(versions), FakeSession(files)


def run(lib, answers=(), interactive=True, **flags):
    config, models, client, session = lib
    full = dict(config, **flags)
    out, ran, answers = [], [], list(answers)
    job = UpdateJob(full, "updates", full["jobs"]["updates"], client,
                    run_job=lambda n: ran.append(n) or True,
                    input_fn=lambda p: answers.pop(0) if answers else "q",
                    output_fn=out.append, interactive=interactive,
                    downloader=dl.Downloader("KEY", "civitai.com", session=session,
                                             sleep=lambda s: None))
    assert job.run()
    return "\n".join(out), ran


def test_offered_only_for_bases_you_use_newest_even_if_older(cross):
    text, _ = run(cross, interactive=False)
    assert "Also for base models you use: 1 version(s) on 1 model(s) (Krea 2 1)" in text
    assert "Pony" not in text


def test_saved_in_that_bases_folder_with_the_category_and_old_kept(cross):
    _, models, *_ = cross
    text, ran = run(cross, ["y"])
    target = models / "Lora" / "krea2" / "style" / "chair_53.safetensors"
    assert target.exists() and "[new folder]" in text  # krea2/style did not exist
    assert "Model 500 · also for Krea 2" in text
    assert (models / "Lora" / "MOSS" / "style" / "chair.safetensors").exists()
    assert "Old version" not in text and ran == ["fetch-all"]


def test_other_version_and_other_folder(cross):
    _, models, *_ = cross
    run(cross, ["v", "2", "o", "Lora/krea2/misc", "y"])
    assert (models / "Lora" / "krea2" / "misc" / "chair_52.safetensors").exists()


def test_never_for_this_base_is_remembered_and_yes_skips_cross_base(cross):
    text, _ = run(cross, ["b"])
    text, _ = run(cross, interactive=False)
    assert "Also for base models you use" not in text
    text, ran = run(cross, interactive=False, yes=True)
    assert not ran


def test_a_reupload_of_your_file_is_not_offered(cross):
    config, models, client, session = cross
    chair = models / "Lora" / "MOSS" / "style" / "chair.safetensors"
    mine = chair.read_bytes()
    client.versions[53]["files"] = [file_entry(53, "chair_53.safetensors", mine)]
    session.files[530] = mine
    text, _ = run(cross, ["y"])
    # v53 is your file again: it falls back to v52, and only v53 is hidden for good
    assert (models / "Lora" / "krea2" / "style" / "chair_52.safetensors").exists()
    decisions = json.loads((models.parent / "update-decisions.json").read_text())
    assert decisions["versions"]["53"]["reason"] == "same_file"


def test_dry_run_writes_no_decisions(cross):
    config, models, client, session = cross
    client.versions[53]["files"] = [file_entry(53, "x.safetensors", b"")]
    client.versions[53]["files"][0]["hashes"]["SHA256"] = hashlib.sha256(
        (models / "Lora" / "MOSS" / "style" / "chair.safetensors").read_bytes()).hexdigest()
    run(cross, dry_run=True)
    assert not (models.parent / "update-decisions.json").exists()


def test_a_checkpoint_in_a_lora_model_is_moved_to_the_checkpoint_folder(cross, monkeypatch):
    config, models, client, session = cross
    ckpt = models.parent / "ckpt.safetensors"
    write_safetensors(str(ckpt), checkpoint())
    data = ckpt.read_bytes()
    client.versions[53]["files"] = [file_entry(53, "chair_full.safetensors", data)]
    session.files[530] = data
    text, _ = run(cross, ["y", "y"])  # download, then "it is a checkpoint; move it?"
    assert "Moved to unet/krea2/chair_full.safetensors" in text
    found = list(models.rglob("chair_full.safetensors"))
    assert found == [models / "unet" / "krea2" / "chair_full.safetensors"]
    run(cross, undo=True)
    assert not list(models.rglob("chair_full.safetensors"))


def test_size_hint_places_a_big_file_in_the_checkpoint_folder(cross, monkeypatch):
    monkeypatch.setattr(job_module, "CHECKPOINT_HINT_BYTES", 1000)
    config, models, client, session = cross
    big = blob(53, 2_000_000)
    client.versions[53]["files"] = [file_entry(53, "chair_full.safetensors", big)]
    text, _ = run(cross, ["s"])
    assert "looks like a full checkpoint" in text
    assert "unet" in text.split("Save as")[1].split("\n")[0]

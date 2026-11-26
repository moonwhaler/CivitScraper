"""Moving models: everything comes along, nothing is overwritten or lost, undo works."""

import json
import os
import time

import pytest

from civitscraper.sorting import mover as mover_module
from civitscraper.sorting.mover import Journal, Mover, plan_move
from civitscraper.utils.hash_cache import get_hash_cache

from .conftest import alpha_lora, companions, dirs, sidecar, tree, write_safetensors


@pytest.fixture
def model(library):
    config, models = library
    src = write_safetensors(models / "Lora" / "Alpha" / "style" / "m.safetensors", alpha_lora(3))
    sidecar(src, "Beta", version_id=555)
    companions(src)
    with open(src + ".rgthree-info.json", "w") as f:
        f.write("{}")
    dst = str(models / "Lora" / "Beta" / "style" / "m.safetensors")
    return config, models, src, dst


def names(path):
    return sorted(os.listdir(path))


def test_model_moves_with_every_companion(model):
    config, models, src, dst = model
    plan = plan_move(src, dst, config)
    assert plan.problem is None and plan.companions == 5
    journal = Journal.create(config)
    assert Mover(config).apply(plan, journal) is None
    assert names(os.path.dirname(dst)) == [
        "m.html", "m.json", "m.preview1.jpeg", "m.preview2.mp4", "m.safetensors",
        "m.safetensors.rgthree-info.json",
    ]
    assert not any(n.startswith("m.") for n in os.listdir(os.path.dirname(src)))


def test_existing_target_blocks_the_whole_model(model):
    config, models, src, dst = model
    os.makedirs(os.path.dirname(dst))
    with open(os.path.join(os.path.dirname(dst), "m.preview1.jpeg"), "wb") as f:
        f.write(b"someone else's preview")
    before = tree(models)
    plan = plan_move(src, dst, config)
    assert plan.problem and "target exists" in plan.problem
    assert Mover(config).apply(plan, Journal.create(config)) == plan.problem
    assert tree(models) == before


def test_failure_midway_rolls_back(model, monkeypatch):
    config, models, src, dst = model
    before = tree(models)
    before_dirs = dirs(models)
    real = mover_module.move_no_clobber
    calls = []

    def flaky(a, b):
        calls.append(a)
        if len(calls) == 3:
            raise OSError(5, "I/O error", b)
        real(a, b)

    monkeypatch.setattr(mover_module, "move_no_clobber", flaky)
    error = Mover(config).apply(plan_move(src, dst, config), Journal.create(config))
    assert error and "I/O error" in error
    assert tree(models) == before  # same inodes, same bytes
    assert dirs(models) == before_dirs  # created folders removed again


def test_undo_restores_the_exact_tree(model):
    config, models, src, dst = model
    before, before_dirs = tree(models), dirs(models)
    journal = Journal.create(config)
    Mover(config).apply(plan_move(src, dst, config), journal)
    journal.finish()
    assert tree(models) != before
    restored, problems = Mover(config).undo(Journal.latest(config))
    assert problems == [] and len(restored) == 1
    assert tree(models) == before
    assert dirs(models) == before_dirs
    assert Journal.load(journal.path).data["state"] == "undone"


def test_undo_takes_previews_added_after_the_move(model):
    config, models, src, dst = model
    journal = Journal.create(config)
    Mover(config).apply(plan_move(src, dst, config), journal)
    journal.finish()
    later = os.path.join(os.path.dirname(dst), "m.preview3.jpeg")
    with open(later, "wb") as f:
        f.write(b"fetched later")
    Mover(config).undo(Journal.latest(config))
    assert os.path.isfile(os.path.join(os.path.dirname(src), "m.preview3.jpeg"))


def test_interrupted_run_is_finished(model):
    config, models, src, dst = model
    plan = plan_move(src, dst, config)
    journal = Journal.create(config)
    journal.models.append({"source": src, "target": dst, "moves": plan.moves,
                           "created_dirs": [], "status": "running"})
    journal.save()
    # crash after the model file and one companion moved
    os.makedirs(os.path.dirname(dst))
    os.rename(src, dst)
    os.rename(plan.moves[1][0], plan.moves[1][1])
    messages = Mover(config).recover(Journal.load(journal.path))
    assert messages and "Finished" in messages[0]
    assert len([n for n in os.listdir(os.path.dirname(dst)) if n.startswith("m.")]) == 6
    assert Journal.load(journal.path).data["state"] == "done"


def test_unfinished_preview_sync_blocks_the_move(model):
    config, models, src, dst = model
    with open(os.path.join(os.path.dirname(src), ".m.civitscraper-sync.json"), "w") as f:
        json.dump({"moves": []}, f)
    assert "preview" in plan_move(src, dst, config).problem


def test_recent_or_downloading_files_are_left_alone(model):
    config, models, src, dst = model
    os.utime(src, None)
    assert "last few minutes" in plan_move(src, dst, config).problem
    old = time.time() - 3600
    os.utime(src, (old, old))
    with open(os.path.join(os.path.dirname(src), "m.G3ny.safetensors.part"), "wb") as f:
        f.write(b"partial")
    assert "download" in plan_move(src, dst, config).problem


def test_unknown_files_sharing_the_name_are_reported_not_moved(model):
    config, models, src, dst = model
    other = os.path.join(os.path.dirname(src), "m.notes.txt")
    with open(other, "w") as f:
        f.write("mine")
    plan = plan_move(src, dst, config)
    assert plan.left_behind == [other]
    Mover(config).apply(plan, Journal.create(config))
    assert os.path.isfile(other)


def test_central_sidecars_follow_the_model_type(model):
    config, models, src, dst = model
    base_dir = models.parent / "meta"
    config = dict(config, output={"base_dir": str(base_dir)})
    os.makedirs(base_dir / "LORA")
    for name in ("m.json", "m.html"):
        os.rename(os.path.join(os.path.dirname(src), name), base_dir / "LORA" / name)
    ck_dst = str(models / "unet" / "alpha" / "m.safetensors")
    plan = plan_move(src, ck_dst, config)
    targets = {os.path.relpath(d, models.parent) for _, d in plan.moves}
    assert "meta/Checkpoint/m.json" in targets and "meta/Checkpoint/m.html" in targets


def test_hash_cache_follows_the_file(model):
    config, models, src, dst = model
    cache = get_hash_cache(config)
    cache.put(src, "sha256", os.stat(src), "abc")
    Mover(config).apply(plan_move(src, dst, config), Journal.create(config))
    assert cache.get(dst, "sha256", os.stat(dst)) == "abc"


def test_dry_run_changes_nothing(model):
    config, models, src, dst = model
    before = tree(models)
    assert Mover(config, dry_run=True).apply(plan_move(src, dst, config),
                                             Journal.create(config)) is None
    assert tree(models) == before

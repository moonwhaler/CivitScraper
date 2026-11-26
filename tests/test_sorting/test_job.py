"""The sort-models job: report, walk-through, --yes, decisions, undo, Krita, regenerate."""

import json
import os

from civitscraper.sorting import job as job_module
from civitscraper.sorting.job import SortJob

from .conftest import beta_lora, checkpoint, sidecar, tree, write_safetensors


def misfile(models):
    """One confident misplacement, one needing a new folder, one cross-root."""
    p = write_safetensors(models / "Lora" / "Alpha" / "style" / "wrong.safetensors", beta_lora(9))
    sidecar(p, "Beta", version_id=999)
    p = write_safetensors(models / "Lora" / "Beta" / "concept" / "twin.safetensors", beta_lora(1))
    sidecar(p, "Gamma", version_id=997)
    p = write_safetensors(models / "Lora" / "Alpha" / "style" / "full.safetensors", checkpoint())
    sidecar(p, "Alpha", "Checkpoint", version_id=995)


def run(config, answers=None, interactive=True, **flags):
    out = []
    answers = list(answers or [])
    full = dict(config, **flags)
    regenerated = []
    job = SortJob(full, "sort", full["jobs"]["sort"],
                  run_job=lambda name: regenerated.append(name) or True,
                  input_fn=lambda prompt: answers.pop(0) if answers else "q",
                  output_fn=out.append, interactive=interactive)
    assert job.run()
    return "\n".join(out), regenerated


def test_without_terminal_it_only_reports(library):
    config, models = library
    misfile(models)
    before = tree(models)
    text, regenerated = run(config, interactive=False)
    assert "Report only" in text and "wrong.safetensors" in text
    assert tree(models) == before and not regenerated


def test_dry_run_reports_and_moves_nothing(library):
    config, models = library
    misfile(models)
    before = tree(models)
    run(config, ["y", "y", "y"], dry_run=True)
    assert tree(models) == before


def test_yes_moves_only_confident_suggestions(library):
    config, models = library
    misfile(models)
    text, regenerated = run(config, interactive=False, yes=True)
    assert (models / "Lora" / "Beta" / "style" / "wrong.safetensors").exists()
    assert (models / "Lora" / "Beta" / "concept" / "twin.safetensors").exists()  # new folder: asked
    assert (models / "Lora" / "Alpha" / "style" / "full.safetensors").exists()  # cross-root: asked
    assert "1 moved" in text
    config["jobs"]["regenerate-html"] = {"type": "scan-paths"}
    misfile_more = write_safetensors(
        models / "Lora" / "Alpha" / "style" / "wrong2.safetensors", beta_lora(8))
    sidecar(misfile_more, "Beta", version_id=990)
    _, regenerated = run(config, interactive=False, yes=True)
    assert regenerated == ["regenerate-html"]


def test_walk_through_moves_keeps_and_remembers(library):
    config, models = library
    misfile(models)
    # order: misplaced (confident first: wrong, then twin), then wrong_root (full)
    text, _ = run(config, ["y", "n", "y"])
    assert (models / "Lora" / "Beta" / "style" / "wrong.safetensors").exists()
    assert (models / "unet" / "alpha" / "full.safetensors").exists()
    assert (models / "unet" / "alpha" / "full.json").exists()
    decisions = json.loads(open(config["sorting"]["decisions_file"]).read())
    assert [d["decision"] for d in decisions["files"].values()] == ["keep"]
    # the kept file is not asked again
    text, _ = run(config, [])
    assert "kept by you" in text and "twin.safetensors" not in text.split("Folders")[1]


def test_other_folder_with_remembered_rule(library):
    config, models = library
    p = write_safetensors(models / "Lora" / "Beta" / "concept" / "twin.safetensors", beta_lora(1))
    sidecar(p, "Gamma", version_id=997)
    run(config, ["o", "Beta/concept", "y"])  # Gamma -> Beta, remembered
    decisions = json.loads(open(config["sorting"]["decisions_file"]).read())
    assert decisions["rules"] == {"lora": {"Gamma": "Beta"}}
    text, _ = run(config, [], interactive=False)
    assert "Everything is where it belongs" in text


def test_batch_answer_applies_to_the_same_folders(library):
    config, models = library
    for n in range(3):
        p = write_safetensors(models / "Lora" / "Alpha" / "style" / f"w{n}.safetensors",
                              beta_lora(10 + n))
        sidecar(p, "Beta", version_id=980 + n)
    text, _ = run(config, ["a"])
    assert all((models / "Lora" / "Beta" / "style" / f"w{n}.safetensors").exists()
               for n in range(3))
    assert "3 moved" in text


def test_conflict_follow_the_file(library):
    config, models = library
    from .conftest import alpha_lora

    p = write_safetensors(models / "Lora" / "Beta" / "concept" / "liar.safetensors", alpha_lora(9))
    sidecar(p, "Beta", version_id=998)
    run(config, ["f"])
    assert (models / "Lora" / "Alpha" / "concept" / "liar.safetensors").exists()
    decisions = json.loads(open(config["sorting"]["decisions_file"]).read())
    (entry,) = decisions["files"].values()
    assert entry["base"] == "Alpha" and entry["family"] == "adapter"
    text, _ = run(config, [], interactive=False)
    assert "Everything is where it belongs" in text


def test_undo_puts_everything_back(library):
    config, models = library
    misfile(models)
    before = tree(models)
    run(config, ["y", "s", "y"])
    assert tree(models) != before
    text, _ = run(config, [], undo=True)
    assert "2 moved back" in text
    assert tree(models) == before
    assert "Nothing to undo" in run(config, [], undo=True)[0]


def test_krita_references_are_updated_and_restored(library, tmp_path, monkeypatch):
    config, models = library
    misfile(models)
    db = tmp_path / "krita" / "database"
    db.mkdir(parents=True)
    (db / "loras.json").write_text(json.dumps([{"id": "Alpha/style/wrong.safetensors"}]))
    config["sorting"]["krita"] = {"loras_file": str(db / "loras.json")}
    monkeypatch.setattr(job_module, "krita_running", lambda: False)
    text, _ = run(config, ["y", "q"])
    assert json.loads((db / "loras.json").read_text())[0]["id"] == "Beta/style/wrong.safetensors"
    assert "1 Krita reference" in text
    run(config, [], undo=True)
    assert json.loads((db / "loras.json").read_text())[0]["id"] == "Alpha/style/wrong.safetensors"


def test_krita_running_without_terminal_is_skipped(library, tmp_path, monkeypatch):
    config, models = library
    misfile(models)
    db = tmp_path / "krita" / "database"
    db.mkdir(parents=True)
    (db / "loras.json").write_text(json.dumps([{"id": "Alpha/style/wrong.safetensors"}]))
    config["sorting"]["krita"] = {"loras_file": str(db / "loras.json")}
    monkeypatch.setattr(job_module, "krita_running", lambda: True)
    text, _ = run(config, interactive=False, yes=True)
    assert "Krita is running" in text
    assert json.loads((db / "loras.json").read_text())[0]["id"] == "Alpha/style/wrong.safetensors"


def test_quit_keeps_moves_done_so_far(library):
    config, models = library
    misfile(models)
    text, _ = run(config, ["y", "q"])
    assert "1 moved" in text
    assert os.path.exists(models / "Lora" / "Beta" / "style" / "wrong.safetensors")


def test_config_keys_are_known(library):
    from civitscraper.config.schema import find_unknown_keys

    config, _ = library
    config = dict(config, yes=True, undo=False, _config_dir="/x", dry_run=True)
    config["sorting"].update(base_folders={"Gamma": {"lora": "Beta"}}, regenerate_job="r",
                             gallery_flag=True)
    assert find_unknown_keys(config) == []


def test_cli_flags_reach_the_config():
    from unittest.mock import patch

    from civitscraper.cli import parse_args

    with patch("sys.argv", ["civitscraper", "-j", "sort", "--yes", "--undo"]):
        args = parse_args()
    assert args.yes and args.undo


def test_executor_runs_the_sort_job(library):
    from unittest.mock import MagicMock

    from civitscraper.jobs.executor import JobExecutor

    config, models = library
    misfile(models)
    config = dict(config, yes=True)
    assert JobExecutor(config, MagicMock()).execute_job("sort")
    assert (models / "Lora" / "Beta" / "style" / "wrong.safetensors").exists()


def test_decisions_file_is_relative_to_the_config(tmp_path):
    from civitscraper.sorting.decisions import decisions_path

    config = {"_config_dir": str(tmp_path), "sorting": {"decisions_file": "d.json"}}
    assert decisions_path(config) == str(tmp_path / "d.json")


def test_walk_through_links_to_civitai_on_both_domains(library):
    config, models = library
    p = write_safetensors(models / "Lora" / "Alpha" / "style" / "wrong.safetensors", beta_lora(9))
    sidecar(p, "Beta", version_id=999, nsfwLevel=16)
    text, _ = run(config, ["s"])
    lines = text.splitlines()
    page = next(i for i, line in enumerate(lines) if line.strip().startswith("Page"))
    assert "https://civitai.red/models/1000?modelVersionId=999" in lines[page]
    assert "https://civitai.com/models/1000?modelVersionId=999" in lines[page + 1]

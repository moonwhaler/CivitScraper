"""The download-updates job: report, walk-through, --yes, old versions, Krita, undo."""

import json
import os

from civitscraper.updates import downloader as dl
from civitscraper.updates.decisions import UpdateDecisions
from civitscraper.updates.job import UpdateJob

from .conftest import tree


def fake_fetch(client, lora):
    """A fetch job: write a sidecar for every new model file."""
    by_name = {}
    for vid, version in client.versions.items():
        for entry in version["files"]:
            by_name[entry["name"]] = (vid, version)

    def run_job(name, ran):
        ran.append(name)
        if name != "fetch-all":
            return True
        for directory, _, names in os.walk(lora):
            for n in names:
                stem, ext = os.path.splitext(n)
                sidecar = os.path.join(directory, stem + ".json")
                if ext == ".safetensors" and not os.path.exists(sidecar) and n in by_name:
                    vid, version = by_name[n]
                    with open(sidecar, "w") as f:
                        json.dump({"id": vid, "modelId": 100 if vid < 30 else 300,
                                   "baseModel": "Flux.1 D", "files": version["files"],
                                   "trainedWords": version.get("trainedWords")}, f)
        return True
    return run_job


def run(library, answers=None, interactive=True, downloader=None, **flags):
    config, models, client, session = library
    full = dict(config, **flags)
    out, ran = [], []
    answers = list(answers or [])
    fetch = fake_fetch(client, models / "Lora")
    job = UpdateJob(
        full, "updates", full["jobs"]["updates"], client,
        run_job=lambda name: fetch(name, ran),
        input_fn=lambda prompt: answers.pop(0) if answers else "q",
        output_fn=out.append, interactive=interactive,
        downloader=downloader or dl.Downloader("KEY", "civitai.com", max_retries=1,
                                               retry_delay=0, session=session,
                                               sleep=lambda s: None),
    )
    assert job.run()
    return "\n".join(out), ran


FOO = os.path.join("Lora", "Flux", "style")


def test_without_terminal_it_only_reports(library):
    _, models, *_ = library
    before = tree(models)
    text, ran = run(library, interactive=False)
    assert "Report only" in text and "foo_v3.safetensors" in text
    assert "early access until 2099-01-01" in text and "civitai.com/models/300" in text
    assert tree(models) == before and not ran


def test_dry_run_changes_nothing(library):
    _, models, *_ = library
    before = tree(models)
    text, _ = run(library, ["y", "k"], dry_run=True)
    assert "Would download" in text and tree(models) == before


def test_walk_through_downloads_the_matching_file_then_archives_and_undo_restores(library):
    config, models, *_ = library
    before = tree(models / "Lora")
    text, ran = run(library, ["y", "a"])
    new = models / FOO / "foo_v3.safetensors"  # the fp16 file, like the local one
    assert new.exists() and "verified" in text
    archived = models / "_archive" / FOO / "foo_v1.safetensors"
    assert archived.exists() and (models / "_archive" / FOO / "foo_v1.json").exists()
    assert not (models / FOO / "foo_v1.safetensors").exists()
    assert ran == ["fetch-all", "regenerate-html"]
    assert "Notes     Better hands" in text and "(was: old trigger)" in text

    text, _ = run(library, undo=True)
    assert tree(models / "Lora") == before
    assert not archived.exists()
    trash = os.listdir(os.path.join(os.environ["XDG_DATA_HOME"], "Trash", "files"))
    assert sorted(trash) == ["foo_v3.json", "foo_v3.safetensors"]


def test_trash_the_old_version_and_undo(library):
    _, models, *_ = library
    before = tree(models / "Lora")
    run(library, ["y", "t"])
    trash = os.path.join(os.environ["XDG_DATA_HOME"], "Trash")
    assert "foo_v1.safetensors" in os.listdir(os.path.join(trash, "files"))
    assert not (models / FOO / "foo_v1.safetensors").exists()
    run(library, undo=True)
    assert tree(models / "Lora") == before


def test_other_version_and_keep(library):
    _, models, *_ = library
    text, ran = run(library, ["v", "2", "y", "k"])
    assert (models / FOO / "foo_v2.safetensors").exists()
    assert (models / FOO / "foo_v1.safetensors").exists()  # kept
    assert ran == ["fetch-all"]  # nothing archived: no regenerate


def test_no_is_remembered_and_hides_the_gallery_flag(library):
    config, models, *_ = library
    text, _ = run(library, ["n"])
    text, _ = run(library, interactive=False)
    assert "foo_v3" not in text and "1 declined or ignored earlier" in text
    decisions = UpdateDecisions.for_config(config)
    versions = [{"is_local": False, "version_id": 12, "created_at": "2026-02-01",
                 "base_model": "Flux.1 D"}]
    assert decisions.declined_ids(100, versions) == {12}  # older than the declined v13


def test_yes_downloads_small_updates_and_keeps_old_versions(library):
    config, models, *_ = library
    config["updates"]["auto_max_size_mb"] = 0
    text, ran = run(library, interactive=False, yes=True)
    assert not (models / FOO / "foo_v3.safetensors").exists() and not ran
    config["updates"]["auto_max_size_mb"] = 1
    text, ran = run(library, interactive=False, yes=True)
    assert (models / FOO / "foo_v3.safetensors").exists()
    assert (models / FOO / "foo_v1.safetensors").exists()
    assert ran == ["fetch-all"]


def test_krita_references_follow_the_new_version_and_undo_reverts(library, tmp_path, monkeypatch):
    config, models, *_ = library
    krita = tmp_path / "krita"
    (krita / "database").mkdir(parents=True)
    (krita / "styles").mkdir()
    loras = krita / "database" / "loras.json"
    entries = [{"id": "Flux/style/foo_v1.safetensors", "name": "Flux/style/foo_v1",
                "source": 0, "format": "safetensors",
                "metadata": {"lora_strength": 0.7, "lora_triggers": "old trigger"}}]
    loras.write_text(json.dumps(entries, indent=2))
    style = {"name": "s", "loras": [{"name": "Flux/style/foo_v1.safetensors", "strength": 0.6,
                                     "enabled": True}]}
    (krita / "styles" / "s.json").write_text(json.dumps(style, indent=4))
    config["sorting"]["krita"] = {"enabled": True, "loras_file": str(loras)}
    monkeypatch.setattr("civitscraper.updates.job.krita_running", lambda: False)

    run(library, ["y", "a"])
    entry = json.loads(loras.read_text())[0]
    assert entry["id"] == "Flux/style/foo_v3.safetensors" and entry["name"] == "Flux/style/foo_v3"
    assert entry["metadata"] == {"lora_strength": 0.7, "lora_triggers": "new trigger"}
    new_style = json.loads((krita / "styles" / "s.json").read_text())
    assert new_style["loras"][0] == {"name": "Flux/style/foo_v3.safetensors", "strength": 0.6,
                                     "enabled": True}

    run(library, undo=True)
    assert json.loads(loras.read_text()) == entries
    assert json.loads((krita / "styles" / "s.json").read_text()) == style


class Interrupting:
    """A downloader that is stopped (Ctrl-C) half-way through the first download."""

    def __init__(self, real):
        self.real = real
        self.stopped = False

    def download(self, url, target, size, sha256, progress=None):
        if not self.stopped:
            self.stopped = True
            with open(target + ".part", "wb") as f:
                f.write(self.first_bytes)
            raise KeyboardInterrupt
        return self.real.download(url, target, size, sha256, progress)


def test_an_interrupted_run_resumes_and_finishes_the_old_version(library):
    _, models, _, session = library
    real = dl.Downloader("KEY", "civitai.com", retry_delay=0, session=session,
                         sleep=lambda s: None)
    stopper = Interrupting(real)
    stopper.first_bytes = session.files[130][:100]
    text, _ = run(library, ["y", "a"], downloader=stopper)
    assert "Stopped" in text and (models / FOO / "foo_v3.safetensors.part").exists()
    text, ran = run(library, ["y"], downloader=stopper)  # "y": resume
    assert "1 interrupted download" in text
    assert (models / FOO / "foo_v3.safetensors").exists()
    assert (models / "_archive" / FOO / "foo_v1.safetensors").exists()
    storage = [c for c in session.calls if "storage" in c[0]]
    assert storage[-1][1]["Range"] == "bytes=100-"
    assert "[1/" not in text  # the resumed version is not offered again


def test_gallery_hides_the_update_flag_of_declined_versions():
    from civitscraper.html.context import ContextBuilder

    cards = [{"model_id": 5, "version_id": 1, "version": "v1", "created_at": "2026-01-01",
              "base_model": "Flux.1 D", "file_path": "/m/a.safetensors",
              "sibling_versions": [{"id": 2, "name": "v2", "createdAt": "2026-02-01",
                                    "baseModel": "Flux.1 D"}]}]
    flagged = ContextBuilder.merge_gallery_models([dict(c) for c in cards])
    assert flagged[0]["update_version"] == "v2"
    hidden = ContextBuilder.merge_gallery_models([dict(c) for c in cards],
                                                 declined=lambda mid, versions: {2})
    assert hidden[0]["update_version"] is None and "update" not in hidden[0]["health"]


def test_configured_archive_folder_relative_to_the_config(library, tmp_path):
    config, models, *_ = library
    config["updates"]["archive_dir"] = "old-models"
    run(library, ["y", "a"])
    assert (tmp_path / "old-models" / FOO / "foo_v1.safetensors").exists()


def test_an_archive_folder_inside_a_scanned_folder_is_refused_before_asking(library):
    config, models, *_ = library
    config["updates"]["archive_dir"] = str(models / "Lora" / "_old")
    prompts = []
    config_answers = ["y", "a", "k"]
    _, _, client, session = library
    out = []
    job = UpdateJob(config, "updates", config["jobs"]["updates"], client,
                    run_job=lambda name: True,
                    input_fn=lambda p: prompts.append(p) or (config_answers.pop(0)
                                                             if config_answers else "q"),
                    output_fn=out.append, interactive=True,
                    downloader=dl.Downloader("KEY", "civitai.com", session=session,
                                             sleep=lambda s: None))
    job.run()
    text = "\n".join(out)
    assert "Archiving is off" in text and "inside a scanned folder" in text
    old_prompt = next(p for p in prompts if "Old version" in p)
    assert "[a]" not in old_prompt
    assert (models / FOO / "foo_v1.safetensors").exists()

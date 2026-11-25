"""Trigger-word helpers of the sync-lora-triggers job."""

import pytest

from civitscraper.jobs.lora_sync import (
    NO_ENTRY,
    SKIPPED,
    UPDATED,
    index_entries,
    trigger_string,
    trigger_words_of,
    update_entry,
)


@pytest.mark.parametrize(
    "words, expected",
    [
        (["a", "b"], "a, b"),
        (["a,", " b, ", "", None, "c"], "a, b, c"),
        ("  single phrase ", "single phrase"),
        (["trailing,"], "trailing"),
    ],
)
def test_trigger_string(words, expected):
    """Lists are comma-joined without doubled or trailing commas."""
    assert trigger_string(words) == expected


def test_trigger_words_prefers_trained_words():
    """The trainedWords field wins; activation text is the fallback (also for [])."""
    assert trigger_words_of({"trainedWords": ["x"], "activation text": "y"}) == ["x"]
    assert trigger_words_of({"trainedWords": [], "activation text": "y"}) == "y"
    assert not trigger_words_of({})


def test_update_entry_matches_by_basename():
    """The entry whose id ends in the model's filename gets the triggers."""
    data = [{"id": "sd/other.safetensors"}, {"id": "sd/sub/foo.safetensors", "metadata": {}}]

    assert update_entry(data, "foo.safetensors", ["a", "b"], overwrite=True) == UPDATED
    assert data[1]["metadata"]["lora_triggers"] == "a, b"
    assert "metadata" not in data[0]


def test_update_entry_respects_overwrite_flag():
    """Existing triggers are kept unless overwrite is on."""
    data = [{"id": "foo.safetensors", "metadata": {"lora_triggers": "keep"}}]

    assert update_entry(data, "foo.safetensors", ["new"], overwrite=False) == SKIPPED
    assert data[0]["metadata"]["lora_triggers"] == "keep"
    assert update_entry(data, "foo.safetensors", ["new"], overwrite=True) == UPDATED
    assert data[0]["metadata"]["lora_triggers"] == "new"


def test_update_entry_creates_metadata_and_reports_missing():
    """A missing metadata dict is created; an unknown file is reported."""
    data = [{"id": "foo.safetensors"}]

    assert update_entry(data, "foo.safetensors", "t", overwrite=True) == UPDATED
    assert data[0]["metadata"] == {"lora_triggers": "t"}
    assert update_entry(data, "bar.safetensors", "t", overwrite=True) == NO_ENTRY


def test_index_keeps_first_entry_per_filename():
    """With duplicate ids, the first entry is the one updated, as before."""
    data = [{"id": "a/foo.safetensors"}, {"id": "b/foo.safetensors"}]
    index = index_entries(data)
    assert update_entry(data, "foo.safetensors", ["x"], overwrite=True, index=index) == UPDATED
    assert data[0]["metadata"]["lora_triggers"] == "x"
    assert "metadata" not in data[1]


def test_sync_reads_files_as_utf8(tmp_path, monkeypatch):
    """loras.json and sidecars are read as UTF-8 whatever the platform default."""
    import builtins
    import json

    from civitscraper.jobs.lora_sync import LoraTriggerSync

    models = tmp_path / "loras"
    models.mkdir()
    (models / "foo.safetensors").write_bytes(b"x")
    (models / "foo.json").write_text(json.dumps({"trainedWords": ["café"]}), encoding="utf-8")
    loras_file = tmp_path / "loras.json"
    loras_file.write_text(json.dumps([{"id": "foo.safetensors"}]), encoding="utf-8")
    encodings = {}
    real_open = builtins.open

    def spy(path, mode="r", *args, **kwargs):
        if str(path).endswith(".json") and "r" in mode and "b" not in mode:
            encodings[str(path)] = kwargs.get("encoding")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    config = {"input_paths": {"l": {"path": str(models), "type": "LORA",
                                    "patterns": ["*.safetensors"]}}}
    job = {"paths": ["l"], "loras_file": str(loras_file)}
    assert LoraTriggerSync(config, "sync", job).run()
    assert encodings and set(encodings.values()) == {"utf-8"}
    saved = json.loads(loras_file.read_text(encoding="utf-8"))
    assert saved[0]["metadata"]["lora_triggers"] == "café"

"""Preview lookup must stay fast in flat folders with thousands of models."""

import os

from civitscraper.scanner import discovery
from civitscraper.scanner.discovery import cached_listings, list_preview_files


def make(tmp_path, names):
    for name in names:
        (tmp_path / name).write_bytes(b"")


def config(tmp_path):
    return {
        "input_paths": {"l": {"path": str(tmp_path), "type": "LORA"}},
        "output": {"images": {"filenames": {"preview": "{model_name}.preview{ext}"}}},
    }


def test_one_listdir_per_folder_inside_scope(tmp_path, monkeypatch):
    names = []
    for i in range(50):
        names += [f"m{i}.safetensors", f"m{i}.preview1.jpeg", f"m{i}.preview2.mp4"]
    make(tmp_path, names)
    calls = {"n": 0}
    real = os.listdir

    def counting(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(discovery.os, "listdir", counting)
    cfg = config(tmp_path)
    with cached_listings():
        results = [list_preview_files(str(tmp_path / f"m{i}.safetensors"), cfg) for i in range(50)]

    assert calls["n"] == 1
    assert all([idx for _, idx, _ in r] == [1, 2] for r in results)


def test_prefix_lookup_does_not_mix_similar_names(tmp_path):
    make(
        tmp_path,
        ["foo.preview1.jpeg", "foo bar.preview1.jpeg", "foo.preview2.png", "foob.preview3.jpeg"],
    )
    cfg = config(tmp_path)
    with cached_listings():
        got = [os.path.basename(p) for p, _, _ in list_preview_files(str(tmp_path / "foo.x"), cfg)]
    assert got == ["foo.preview1.jpeg", "foo.preview2.png"]


def test_outside_scope_listing_is_always_fresh(tmp_path):
    cfg = config(tmp_path)
    model = str(tmp_path / "m.safetensors")
    with cached_listings():
        assert list_preview_files(model, cfg) == []
    (tmp_path / "m.preview1.jpeg").write_bytes(b"")
    assert len(list_preview_files(model, cfg)) == 1


def test_scope_clears_cache_on_exit(tmp_path):
    cfg = config(tmp_path)
    model = str(tmp_path / "m.safetensors")
    with cached_listings():
        list_preview_files(model, cfg)
    assert discovery._listing_cache == {}

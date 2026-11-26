"""Krita LoRA references follow moved files; exact matches only, with a backup."""

import json
import os

from civitscraper.sorting.krita import KritaReferences


def setup_krita(tmp_path):
    db = tmp_path / "krita" / "database"
    styles = tmp_path / "krita" / "styles"
    db.mkdir(parents=True)
    styles.mkdir()
    loras = [
        {"id": "Alpha/style/m.safetensors", "name": "Alpha/style/m", "format": "lora"},
        {"id": "Alpha/style/m.safetensors.bak", "name": "other"},
    ]
    (db / "loras.json").write_text(json.dumps(loras, indent=2) + "\n")
    style = {"name": "s", "loras": [{"name": "Alpha/style/m.safetensors", "strength": 1.0},
                                    {"name": "m.safetensors", "strength": 0.5}]}
    (styles / "s.json").write_text(json.dumps(style, indent=4))
    config = {"sorting": {"krita": {"loras_file": str(db / "loras.json")}}}
    return config, db, styles


def test_rewrites_exact_references_and_keeps_a_backup(tmp_path):
    config, db, styles = setup_krita(tmp_path)
    krita = KritaReferences(config)
    assert krita.available
    changed = krita.rewrite([("Alpha/style/m.safetensors", "Beta/style/m.safetensors")])
    assert changed == 2
    loras = json.loads((db / "loras.json").read_text())
    assert loras[0]["id"] == "Beta/style/m.safetensors"
    assert loras[1]["id"] == "Alpha/style/m.safetensors.bak"  # not an exact match
    assert loras[0]["name"] == "Alpha/style/m"  # display name untouched
    style = json.loads((styles / "s.json").read_text())
    names = [entry["name"] for entry in style["loras"]]
    assert names == ["Beta/style/m.safetensors", "m.safetensors"]
    assert (styles / "s.json").read_text().startswith('{\n    "name"')  # indent kept
    assert any(n.startswith("loras.json.bak-") for n in os.listdir(db))


def test_reverse_rewrite_undoes_it(tmp_path):
    config, db, _ = setup_krita(tmp_path)
    original = (db / "loras.json").read_text()
    krita = KritaReferences(config)
    krita.rewrite([("Alpha/style/m.safetensors", "Beta/style/m.safetensors")])
    krita.rewrite([("Beta/style/m.safetensors", "Alpha/style/m.safetensors")])
    assert (db / "loras.json").read_text() == original


def test_windows_separators_match_too(tmp_path):
    config, db, _ = setup_krita(tmp_path)
    data = json.loads((db / "loras.json").read_text())
    data[0]["id"] = "Alpha\\style\\m.safetensors"
    (db / "loras.json").write_text(json.dumps(data))
    KritaReferences(config).rewrite([("Alpha/style/m.safetensors", "Beta/style/m.safetensors")])
    assert json.loads((db / "loras.json").read_text())[0]["id"] == "Beta\\style\\m.safetensors"


def test_default_paths_come_from_the_trigger_sync_job(tmp_path):
    config, db, styles = setup_krita(tmp_path)
    config = {"jobs": {"sync": {"type": "sync-lora-triggers",
                                "loras_file": str(db / "loras.json")}}}
    krita = KritaReferences(config)
    assert krita.loras_file == str(db / "loras.json")
    assert krita.styles_dir == str(styles)

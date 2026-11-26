"""Freedesktop Trash: trashinfo record, unique names, restore."""

import os

from civitscraper.utils import trash


def test_trash_and_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    original = tmp_path / "models" / "a b.safetensors"
    original.parent.mkdir()
    original.write_bytes(b"one")
    where, info = trash.trash(str(original))
    assert not original.exists()
    assert where == str(tmp_path / "xdg" / "Trash" / "files" / "a b.safetensors")
    record = open(info).read()
    assert record.startswith("[Trash Info]\nPath=") and "a%20b.safetensors" in record
    assert "DeletionDate=" in record

    original.write_bytes(b"two")  # same name again: a unique name in the Trash
    where2, info2 = trash.trash(str(original))
    assert where2 != where and os.path.basename(where2) == "a b.2.safetensors"

    trash.restore(where2, info2, str(original))
    assert original.read_bytes() == b"two" and not os.path.exists(info2)

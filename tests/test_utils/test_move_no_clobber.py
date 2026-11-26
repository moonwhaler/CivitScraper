"""move_no_clobber: an existing target is never replaced."""

import errno
import os

import pytest

from civitscraper.utils import fs
from civitscraper.utils.fs import move_no_clobber


def test_moves_file(tmp_path):
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_bytes(b"data")
    move_no_clobber(str(src), str(dst))
    assert not src.exists() and dst.read_bytes() == b"data"


def test_existing_target_is_kept(tmp_path):
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        move_no_clobber(str(src), str(dst))
    assert src.read_bytes() == b"new" and dst.read_bytes() == b"old"


def test_symlink_is_moved_as_link(tmp_path):
    real = tmp_path / "real"
    real.write_bytes(b"x")
    link = tmp_path / "link"
    link.symlink_to(real)
    move_no_clobber(str(link), str(tmp_path / "moved"))
    assert os.path.islink(tmp_path / "moved") and real.exists()


def test_falls_back_to_rename_without_hard_links(tmp_path, monkeypatch):
    def no_link(*args, **kwargs):
        raise OSError(errno.EPERM, "not supported")

    monkeypatch.setattr(fs.os, "link", no_link)
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_bytes(b"data")
    move_no_clobber(str(src), str(dst))
    assert dst.read_bytes() == b"data" and not src.exists()


def test_cross_device_error_changes_nothing(tmp_path, monkeypatch):
    def cross(*args, **kwargs):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(fs.os, "link", cross)
    src = tmp_path / "a"
    src.write_bytes(b"data")
    with pytest.raises(OSError):
        move_no_clobber(str(src), str(tmp_path / "b"))
    assert src.exists() and not (tmp_path / "b").exists()

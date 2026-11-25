"""Tests for atomic file writes."""

import os
import stat
import sys
import threading
from unittest.mock import MagicMock

import pytest
import requests

from civitscraper.api.request import RequestHandler
from civitscraper.utils import fs
from civitscraper.utils.fs import atomic_write


def test_writes_str_bytes_and_chunks(tmp_path):
    target = tmp_path / "sub" / "a.txt"
    atomic_write(str(target), "hällo")
    assert target.read_text(encoding="utf-8") == "hällo"
    atomic_write(str(target), b"bytes")
    assert target.read_bytes() == b"bytes"
    atomic_write(str(target), iter([b"a", b"", b"b"]))
    assert target.read_bytes() == b"ab"


def test_failure_keeps_existing_file_and_leaves_no_temp(tmp_path):
    target = tmp_path / "a.json"
    target.write_text("old")

    def broken():
        yield b"partial"
        raise RuntimeError("connection dropped")

    with pytest.raises(RuntimeError):
        atomic_write(str(target), broken())

    assert target.read_text() == "old"
    assert os.listdir(tmp_path) == ["a.json"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_new_files_get_umask_mode_not_private(tmp_path):
    target = tmp_path / "new.html"
    atomic_write(str(target), "x")
    assert stat.S_IMODE(target.stat().st_mode) == 0o666 & ~fs._UMASK


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_existing_file_mode_is_preserved(tmp_path):
    target = tmp_path / "a.json"
    target.write_text("old")
    os.chmod(target, 0o640)
    atomic_write(str(target), "new")
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlink_is_written_through(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("old")
    link = tmp_path / "link.json"
    link.symlink_to(real)

    atomic_write(str(link), "new")

    assert link.is_symlink()
    assert real.read_text() == "new"


def test_concurrent_writers_to_same_path(tmp_path):
    target = tmp_path / "shared.json"
    payloads = [str(i) * 10000 for i in range(8)]
    threads = [threading.Thread(target=atomic_write, args=(str(target), p)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert target.read_text() in payloads
    assert os.listdir(tmp_path) == ["shared.json"]


def test_replace_retries_on_permission_error(tmp_path, monkeypatch):
    target = tmp_path / "a.txt"
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("locked by indexer")
        real_replace(src, dst)

    monkeypatch.setattr(fs.os, "replace", flaky)
    monkeypatch.setattr(fs, "_REPLACE_RETRY_DELAY", 0)

    atomic_write(str(target), "ok")

    assert calls["n"] == 2
    assert target.read_text() == "ok"


def test_interrupted_download_leaves_no_preview(tmp_path):
    handler = RequestHandler(
        base_url="https://example.invalid",
        rate_limiter=MagicMock(),
        circuit_breaker=MagicMock(),
    )

    def chunks(chunk_size):
        yield b"\xff\xd8partial-jpeg"
        raise requests.exceptions.ChunkedEncodingError("connection reset")

    response = MagicMock()
    response.headers = {"Content-Type": "image/jpeg"}
    response.iter_content.side_effect = chunks
    handler.session = MagicMock()
    handler.session.get.return_value = response
    target = tmp_path / "foo.preview1.jpeg"

    ok, _ = handler.download("https://example.invalid/1.jpeg", str(target))

    assert not ok
    assert os.listdir(tmp_path) == []


def test_api_cache_prunes_expired_entries_but_not_subcaches(tmp_path, monkeypatch):
    import time as _time

    from civitscraper.utils import cache as cache_mod
    from civitscraper.utils.cache import CacheManager

    monkeypatch.setattr(cache_mod, "PRUNE_THRESHOLD", 3)
    old = _time.time() - 10_000
    for i in range(5):
        f = tmp_path / f"{i}.json"
        f.write_text("{}")
        if i < 4:
            os.utime(f, (old, old))
    sub = tmp_path / "file_hashes"
    sub.mkdir()
    (sub / "hashes.json").write_text("{}")
    os.utime(sub / "hashes.json", (old, old))

    CacheManager({"scanner": {"cache_dir": str(tmp_path), "cache_validity": 60}})

    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["4.json"]
    assert (sub / "hashes.json").exists()

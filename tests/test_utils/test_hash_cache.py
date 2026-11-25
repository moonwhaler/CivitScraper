"""Hash cache: reuse hashes of unchanged files, never of changed ones."""

import hashlib
import os

from civitscraper.scanner.file_processor import ModelFileProcessor
from civitscraper.utils import hash_cache as hc
from civitscraper.utils.hash_cache import HashCache


def processor(tmp_path, monkeypatch, rehash=False):
    monkeypatch.setattr(hc, "_instances", {})
    config = {"scanner": {"cache_dir": str(tmp_path / "cache"), "rehash": rehash}}
    return ModelFileProcessor(config)


def count_hashes(monkeypatch):
    import civitscraper.scanner.file_processor as fp

    calls = {"n": 0}
    real = fp.compute_file_hash

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(fp, "compute_file_hash", counting)
    return calls


def test_unchanged_file_is_not_rehashed_across_runs(tmp_path, monkeypatch):
    model = tmp_path / "m.safetensors"
    model.write_bytes(b"weights")
    calls = count_hashes(monkeypatch)

    first = processor(tmp_path, monkeypatch)
    h1 = first.process(str(model)).file_hash
    first.flush()
    second = processor(tmp_path, monkeypatch)  # fresh instance = next run
    h2 = second.process(str(model)).file_hash

    assert h1 == h2 == hashlib.sha256(b"weights").hexdigest().upper()
    assert calls["n"] == 1
    assert (tmp_path / "cache" / "file_hashes" / "hashes.json").is_file()


def test_changed_size_or_mtime_is_rehashed(tmp_path, monkeypatch):
    model = tmp_path / "m.safetensors"
    model.write_bytes(b"aaaa")
    p = processor(tmp_path, monkeypatch)
    p.process(str(model))

    model.write_bytes(b"bbbb")  # same size
    st = model.stat()
    os.utime(model, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

    assert p.process(str(model)).file_hash == hashlib.sha256(b"bbbb").hexdigest().upper()


def test_rehash_flag_bypasses_cache(tmp_path, monkeypatch):
    model = tmp_path / "m.safetensors"
    model.write_bytes(b"x")
    processor(tmp_path, monkeypatch).process(str(model))
    calls = count_hashes(monkeypatch)

    processor(tmp_path, monkeypatch, rehash=True).process(str(model))

    assert calls["n"] == 1


def test_corrupt_cache_file_is_ignored(tmp_path):
    path = tmp_path / "file_hashes" / "hashes.json"
    path.parent.mkdir()
    path.write_text("{not json")
    cache = HashCache(str(tmp_path))
    assert cache.get("x", "sha256", os.stat(path)) is None


def test_cache_file_is_outside_api_cache_prune_glob(tmp_path):
    cache = HashCache(str(tmp_path))
    assert os.path.dirname(cache.path) != str(tmp_path)
    assert not list(tmp_path.glob("*.json"))

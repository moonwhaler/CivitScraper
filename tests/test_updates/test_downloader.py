"""The downloader: key only to CivitAI, resume, hash check, never overwrite."""

import hashlib
import os

from civitscraper.updates import downloader as dl

from .conftest import FakeSession, blob


def make(files, key="KEY"):
    session = FakeSession(files)
    return dl.Downloader(key, "civitai.com", max_retries=2, retry_delay=0, session=session,
                         sleep=lambda s: None), session


URL = "https://civitai.com/api/download/models/1?fileId=10"


def sha(data):
    return hashlib.sha256(data).hexdigest().upper()


def test_downloads_and_verifies_and_sends_the_key_only_to_civitai(tmp_path):
    data = blob(1, 5000)
    d, session = make({10: data})
    target = str(tmp_path / "m.safetensors")
    result = d.download(URL, target, len(data), sha(data))
    assert result.ok and result.verified
    assert open(target, "rb").read() == data
    assert not os.path.exists(target + ".part")
    api, storage = session.calls
    assert api[1]["Authorization"] == "Bearer KEY"
    assert "Authorization" not in storage[1]


def test_url_of_the_chosen_file_keeps_its_file_id():
    entry = {"id": 7, "downloadUrl": "https://civitai.red/api/download/models/3?fileId=7"}
    assert dl.download_url(entry, 3, "https://civitai.com/api/v1") == (
        "https://civitai.com/api/download/models/3?fileId=7")
    assert dl.download_url({"id": 8}, 3, "https://civitai.com/api/v1").endswith("/3?fileId=8")


def test_api_refusals(tmp_path):
    d, session = make({10: b"x"})
    session.api_status[10] = 403
    assert d.download(URL, str(tmp_path / "a"), 1, None).status == dl.EARLY_ACCESS
    session.api_status[10] = 404
    assert d.download(URL, str(tmp_path / "a"), 1, None).status == dl.NOT_FOUND
    no_key, _ = make({10: b"x"}, key=None)
    assert no_key.download(URL, str(tmp_path / "a"), 1, None).status == dl.UNAUTHORIZED
    assert not os.listdir(tmp_path)


def test_resumes_after_a_dropped_connection(tmp_path):
    data = blob(1, 6000)
    d, session = make({10: data})
    session.drop_once[10] = 2048
    target = str(tmp_path / "m.safetensors")
    result = d.download(URL, target, len(data), sha(data))
    assert result.ok and open(target, "rb").read() == data
    ranges = [c[1].get("Range") for c in session.calls if "storage" in c[0]]
    assert ranges[0] is None and ranges[1].startswith("bytes=")


def test_resumes_a_part_file_from_an_earlier_run(tmp_path):
    data = blob(1, 6000)
    target = str(tmp_path / "m.safetensors")
    with open(target + ".part", "wb") as f:
        f.write(data[:3000])
    d, session = make({10: data})
    assert d.download(URL, target, len(data), sha(data)).ok
    assert open(target, "rb").read() == data
    assert session.calls[-1][1]["Range"] == "bytes=3000-"


def test_a_server_ignoring_the_range_starts_over(tmp_path):
    data = blob(1, 6000)
    target = str(tmp_path / "m.safetensors")
    with open(target + ".part", "wb") as f:
        f.write(b"junk" * 100)
    d, session = make({10: data})
    session.ignore_range = True
    assert d.download(URL, target, len(data), sha(data)).ok
    assert open(target, "rb").read() == data


def test_hash_mismatch_removes_only_the_part_file(tmp_path):
    data = blob(1, 5000)
    d, _ = make({10: data})
    target = str(tmp_path / "m.safetensors")
    result = d.download(URL, target, len(data), sha(b"other"))
    assert result.status == dl.HASH_MISMATCH
    assert not os.listdir(tmp_path)


def test_size_mismatch_aborts(tmp_path):
    d, _ = make({10: blob(1, 9000)})
    result = d.download(URL, str(tmp_path / "m"), 4000, None)
    assert result.status == dl.SIZE_MISMATCH and not os.listdir(tmp_path)


def test_an_existing_file_is_never_replaced(tmp_path):
    target = tmp_path / "m.safetensors"
    target.write_bytes(b"mine")
    d, session = make({10: blob(1)})
    assert d.download(URL, str(target), 4096, None).status == dl.EXISTS
    assert target.read_bytes() == b"mine" and not session.calls

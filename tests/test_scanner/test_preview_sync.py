"""Preview sync: files follow CivitAI's images, nothing is ever deleted."""

import json
import os
import struct
import zlib
from unittest.mock import MagicMock

import pytest

from civitscraper.scanner.image_manager import ARCHIVED, ORPHAN, ImageManager
from civitscraper.scanner.sidecar import NAMESPACE
from civitscraper.utils.imagesize import image_size


def png(width, height, tag=b""):
    """A tiny valid PNG of the given size (content tagged so files differ)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"tEXt", b"t\x00" + tag)
        + chunk(b"IEND", b"")
    )


def img(n, w=100, h=150, **extra):
    return {
        "url": f"https://image.civitai.com/key/uuid-{n}/original=true/{n}.jpeg",
        "width": w,
        "height": h,
        "meta": {"prompt": f"prompt {n}"},
        **extra,
    }


@pytest.fixture
def setup(tmp_path):
    config = {"output": {"images": {"max_count": 3}}}
    api = MagicMock()

    def download(url, path):
        n = url.rsplit("/", 1)[1].split(".")[0]
        with open(path, "wb") as f:
            f.write(png(100, 150, f"new {n}".encode()))
        return True, "image/png"

    api.download_image.side_effect = download
    manager = ImageManager(config, api)
    model = tmp_path / "foo.safetensors"
    model.write_bytes(b"x")
    return manager, str(model), tmp_path


def write_previews(tmp_path, *tags, size=(100, 150)):
    for n, tag in enumerate(tags, 1):
        if tag is not None:
            (tmp_path / f"foo.preview{n}.jpeg").write_bytes(png(*size, tag.encode()))


def content(tmp_path):
    """Preview number -> tag stored in the file (which picture it is)."""
    result = {}
    for name in sorted(os.listdir(tmp_path)):
        if name.startswith("foo.preview"):
            data = (tmp_path / name).read_bytes()
            tag = data.split(b"tEXtt\x00", 1)[1].split(b"\x00\x00", 1)[0]
            result[int(name.split("preview")[1].split(".")[0])] = tag[
                : tag.find(b"\x00") if b"\x00" in tag else None
            ]
    return result


def sync(manager, model, old_images, fresh_images, source="showcase", **old_extra):
    old = {"images": old_images, **old_extra}
    merged = manager.sync_previews(model, old, {"images": fresh_images}, source)
    manager.finish_sync(model)
    return merged


def prompts(images):
    return [(i.get("meta") or {}).get("prompt") for i in images]


def test_reorder_renames_files_so_prompts_stay_with_their_picture(setup):
    manager, model, d = setup
    write_previews(d, "pic1", "pic2", "pic3")
    merged = sync(manager, model, [img(1), img(2), img(3)], [img(3), img(1), img(2)])
    assert prompts(merged["images"]) == ["prompt 3", "prompt 1", "prompt 2"]
    files = {n: (d / f"foo.preview{n}.jpeg").read_bytes() for n in (1, 2, 3)}
    assert b"pic3" in files[1] and b"pic1" in files[2] and b"pic2" in files[3]
    assert merged[NAMESPACE]["previewsSynced"] is True


def test_image_removed_on_civitai_is_archived_and_kept(setup):
    manager, model, d = setup
    write_previews(d, "pic1", "pic2")
    merged = sync(manager, model, [img(1), img(2)], [img(2), img(4)])
    assert prompts(merged["images"]) == ["prompt 2", "prompt 4", "prompt 1"]
    assert merged["images"][2][ARCHIVED] is True
    assert b"pic1" in (d / "foo.preview3.jpeg").read_bytes()  # archived, still on disk
    assert b"pic2" in (d / "foo.preview1.jpeg").read_bytes()
    assert not (d / "foo.preview2.jpeg").exists()  # slot for the new image, downloaded later

    manager.download_images(model, merged)
    assert b"new 4" in (d / "foo.preview2.jpeg").read_bytes()
    assert b"pic1" in (d / "foo.preview3.jpeg").read_bytes()  # archived, never re-downloaded


def test_failed_download_loses_no_file(setup):
    manager, model, d = setup
    write_previews(d, "pic1")
    merged = sync(manager, model, [img(1)], [img(5), img(1)])
    manager.api_client.download_image.side_effect = lambda url, path: (False, None)
    manager.download_images(model, merged)
    assert b"pic1" in (d / "foo.preview2.jpeg").read_bytes()
    assert not (d / "foo.preview1.jpeg").exists()


def test_lowered_max_count_and_unknown_files_delete_nothing(setup):
    manager, model, d = setup
    write_previews(d, "pic1", "pic2", "pic3", "pic4", "stray5")
    before = sorted(os.listdir(d))
    merged = sync(
        manager, model, [img(1), img(2), img(3), img(4)], [img(1), img(2), img(3), img(4)]
    )
    assert len([n for n in os.listdir(d) if n.startswith("foo.preview")]) == 5
    assert merged["images"][3] == img(4)  # still on CivitAI, past max_count 3: not archived
    assert merged["images"][4] == {ARCHIVED: True, ORPHAN: True}
    assert sorted(os.listdir(d)) == before


def test_legacy_file_with_wrong_size_becomes_an_orphan(setup):
    manager, model, d = setup
    write_previews(d, "pic1")
    write_previews(d, None, "other", size=(640, 480))  # preview2 is not image 2
    merged = sync(manager, model, [img(1), img(2)], [img(1), img(2)])
    assert prompts(merged["images"][:2]) == ["prompt 1", "prompt 2"]
    assert merged["images"][2] == {ARCHIVED: True, ORPHAN: True}
    assert b"other" in (d / "foo.preview3.jpeg").read_bytes()
    assert not (d / "foo.preview2.jpeg").exists()  # downloaded again (correct picture)


def test_second_file_with_the_same_number_is_kept(setup):
    manager, model, d = setup
    write_previews(d, "pic1")
    (d / "foo.preview1.mp4").write_bytes(b"video")
    merged = sync(manager, model, [img(1)], [img(1)])
    assert len(merged["images"]) == 2 and merged["images"][1][ORPHAN]
    names = sorted(n for n in os.listdir(d) if n.startswith("foo.preview"))
    assert len(names) == 2 and (d / "foo.preview1.jpeg").exists()


def test_feed_images_keep_their_numbers_and_only_fill_gaps(setup):
    manager, model, d = setup
    old = [img(1, id=1), img(2, id=2), img(3, id=3)]
    write_previews(d, "pic1", None, "pic3")
    fresh = [img(7, id=7), img(3, id=3), img(8, id=8)]
    merged = sync(manager, model, old, fresh, source="feed")
    assert prompts(merged["images"]) == ["prompt 1", "prompt 7", "prompt 3"]
    assert ARCHIVED not in merged["images"][0]  # never archived from a feed
    assert b"pic1" in (d / "foo.preview1.jpeg").read_bytes()
    assert b"pic3" in (d / "foo.preview3.jpeg").read_bytes()


def test_mirror_mode_renames_nothing(setup):
    manager, model, d = setup
    write_previews(d, "pic1", "pic2")
    merged = manager.sync_previews(
        model, {"images": [img(1), img(2)]}, {"images": [img(2), img(1)]}, "showcase", mirror=True
    )
    assert prompts(merged["images"]) == ["prompt 1", "prompt 2"]
    assert b"pic1" in (d / "foo.preview1.jpeg").read_bytes()


def test_interrupted_sync_is_finished_next_run(setup):
    manager, model, d = setup
    write_previews(d, "pic1", "pic2")
    plan = manager.plan_sync(model, {"images": [img(1), img(2)]}, [img(2), img(1)], "showcase")
    # Simulate a crash after phase 1: both files under temporary names
    journal = manager._journal_path(model)
    moves = [
        (s, os.path.join(os.path.dirname(s), "." + os.path.basename(s) + ".civitscraper-move"), t)
        for s, t in plan.moves
    ]
    with open(journal, "w") as f:
        json.dump({"moves": moves, "images": plan.images, "phase": 2}, f)
    for s, t, _ in moves:
        os.rename(s, t)

    merged = sync(manager, model, [img(1), img(2)], [img(2), img(1)])
    assert prompts(merged["images"]) == ["prompt 2", "prompt 1"]
    assert b"pic2" in (d / "foo.preview1.jpeg").read_bytes()
    assert b"pic1" in (d / "foo.preview2.jpeg").read_bytes()
    assert not os.path.exists(journal)


def test_dry_run_changes_nothing(setup):
    manager, model, d = setup
    manager.dry_run = True
    write_previews(d, "pic1", "pic2")
    merged = sync(manager, model, [img(1), img(2)], [img(2), img(1)])
    assert merged["images"] == [img(2), img(1)]
    assert b"pic1" in (d / "foo.preview1.jpeg").read_bytes()


def test_video_download_never_replaces_an_existing_mp4(setup):
    manager, model, d = setup
    (d / "foo.preview1.mp4").write_bytes(b"old video")
    path = manager._perform_download("https://x/1.jpeg", str(d / "foo.preview1.jpeg"), 0, 1)
    manager.api_client.download_image.side_effect = lambda url, p: (
        open(p, "wb").write(b"v") and (True, "video/mp4")
    )
    path = manager._perform_download("https://x/1.jpeg", str(d / "foo.preview1.jpeg"), 0, 1)
    assert (d / "foo.preview1.mp4").read_bytes() == b"old video"
    assert path.endswith(".jpeg")


def test_image_size_reads_png_header(tmp_path):
    (tmp_path / "a.png").write_bytes(png(321, 123))
    assert image_size(str(tmp_path / "a.png")) == (321, 123)
    (tmp_path / "b.bin").write_bytes(b"nope")
    assert image_size(str(tmp_path / "b.bin")) is None

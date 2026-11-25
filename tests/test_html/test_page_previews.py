"""Model page previews: files by preview number, NSFW flags, archived previews."""

from civitscraper.html.images import ImageHandler, image_is_nsfw
from civitscraper.scanner.metadata_manager import MetadataManager


def _config(tmp_path, max_count=None):
    models = tmp_path / "loras"
    models.mkdir(exist_ok=True)
    config = {
        "api": {"nsfw": {"level_threshold": 4}},
        "input_paths": {"l": {"path": str(models), "type": "LORA", "patterns": ["*.safetensors"]}},
        "output": {"images": {"max_count": max_count}},
    }
    model = models / "foo.safetensors"
    model.write_bytes(b"x")
    return config, models, str(model)


def _img(n, **extra):
    return {"url": f"https://image.civitai.com/k/uuid-{n}/original=true/{n}.jpeg",
            "meta": {"prompt": f"prompt {n}"}, **extra}


def test_files_are_found_whatever_their_extension(tmp_path):
    config, models, model = _config(tmp_path)
    (models / "foo.preview1.png").write_bytes(b"x")
    (models / "foo.preview2.mp4").write_bytes(b"x")
    images = ImageHandler(config).get_image_paths(model, {"images": [_img(1), _img(2)]})
    assert [(i["path"], i["prompt"], i["is_video"]) for i in images] == [
        ("foo.preview1.png", "prompt 1", False),
        ("foo.preview2.mp4", "prompt 2", True),
    ]


def test_missing_preview_does_not_shift_the_others(tmp_path):
    config, models, model = _config(tmp_path)
    (models / "foo.preview2.jpeg").write_bytes(b"x")
    images = ImageHandler(config).get_image_paths(model, {"images": [_img(1), _img(2)]})
    assert [i["prompt"] for i in images] == ["prompt 2"]


def test_archived_previews_are_shown_after_current_ones_beyond_max_count(tmp_path):
    config, models, model = _config(tmp_path, max_count=1)
    for n in (1, 2, 3):
        (models / f"foo.preview{n}.jpeg").write_bytes(b"x")
    meta = {"images": [_img(1), _img(2), _img(3, civitscraperArchived=True)]}
    images = ImageHandler(config).get_image_paths(model, meta)
    assert [(i["prompt"], i["archived"]) for i in images] == [
        ("prompt 1", False), ("prompt 3", True)]


def test_nsfw_flag_from_level_or_feed_boolean():
    assert image_is_nsfw({"nsfwLevel": 8}, 4)
    assert not image_is_nsfw({"nsfwLevel": 1, "nsfw": True}, 4)  # the level decides
    assert image_is_nsfw({"nsfw": True}, 4)  # older feed sidecars: boolean only
    assert not image_is_nsfw({}, 4)


def test_feed_images_keep_their_level(tmp_path):
    from unittest.mock import MagicMock

    api = MagicMock()
    api.get_images.return_value = {"items": [{"id": 1, "url": "u", "nsfwLevel": 16,
                                              "type": "video"}]}
    manager = MetadataManager({"scanner": {"cache_dir": str(tmp_path)}}, api)
    (image,) = manager._fetch_nsfw_images(5, False)
    assert image["nsfwLevel"] == 16 and image["type"] == "video" and image["nsfw"] is True
    api.get_images.side_effect = RuntimeError("down")
    assert manager._fetch_nsfw_images(5, False) is None

"""Tests for the NSFW image-feed fallback in MetadataManager.fetch_metadata."""

from unittest.mock import MagicMock

from civitscraper.scanner.metadata_manager import MetadataManager


def make_manager():
    api = MagicMock()
    config = {"api": {"nsfw": {"level_threshold": 4, "browsing_level": "X"}}, "output": {}}
    return MetadataManager(config, api), api


SFW_INLINE = [{"id": 1, "url": "https://image.civitai.com/a.jpeg", "nsfwLevel": 1}]
NSFW_VERSION = {"id": 11745, "modelId": 6424, "nsfwLevel": 60, "images": SFW_INLINE}
SFW_VERSION = {"id": 200, "modelId": 7, "nsfwLevel": 1, "images": SFW_INLINE}

FEED = {
    "items": [
        {
            "id": 99,
            "url": "https://image.civitai.com/x.jpeg",
            "nsfwLevel": 8,
            "width": 512,
            "height": 768,
            "hash": "abc",
            "meta": {"prompt": "p"},
        }
    ]
}


def test_nsfw_model_replaces_images_with_feed():
    mgr, api = make_manager()
    api.get_model_version_by_hash.return_value = dict(NSFW_VERSION)
    api.get_images.return_value = FEED

    metadata = mgr.fetch_metadata("HASH")

    api.get_images.assert_called_once()
    _, kwargs = api.get_images.call_args
    assert kwargs["model_version_id"] == 11745
    assert kwargs["nsfw"] == "X"
    assert len(metadata["images"]) == 1
    img = metadata["images"][0]
    assert img["url"] == "https://image.civitai.com/x.jpeg"
    assert img["nsfw"] is True          # level 8 >= threshold 4
    assert img["meta"] == {"prompt": "p"}


def test_sfw_model_keeps_inline_images():
    mgr, api = make_manager()
    api.get_model_version_by_hash.return_value = dict(SFW_VERSION)

    metadata = mgr.fetch_metadata("HASH")

    api.get_images.assert_not_called()
    assert metadata["images"] == SFW_INLINE


def test_feed_failure_falls_back_to_inline():
    mgr, api = make_manager()
    api.get_model_version_by_hash.return_value = dict(NSFW_VERSION)
    api.get_images.side_effect = RuntimeError("boom")

    metadata = mgr.fetch_metadata("HASH")

    assert metadata["images"] == SFW_INLINE  # unchanged on failure


def test_empty_feed_falls_back_to_inline():
    mgr, api = make_manager()
    api.get_model_version_by_hash.return_value = dict(NSFW_VERSION)
    api.get_images.return_value = {"items": []}

    metadata = mgr.fetch_metadata("HASH")

    assert metadata["images"] == SFW_INLINE

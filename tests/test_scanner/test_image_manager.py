"""Tests for ImageManager preview file handling (issue #2: Invalid preview filename)."""

from unittest.mock import MagicMock

import pytest

from civitscraper.scanner.image_manager import ImageManager


def make_manager(tmp_path, max_count=1, skip_existing=False, dry_run=False):
    config = {
        "output": {
            "images": {
                "path": "{model_dir}",
                "max_count": max_count,
                "filenames": {"preview": "{model_name}.preview{ext}"},
            }
        },
        "skip_existing": skip_existing,
        "dry_run": dry_run,
    }
    api = MagicMock()
    manager = ImageManager(config, api)
    model_path = tmp_path / "model.safetensors"
    model_path.write_bytes(b"")
    return manager, model_path


def test_clean_up_ignores_non_numbered_preview_file(tmp_path):
    """A stray preview file without a trailing number (e.g. left over from a
    misconfigured filename pattern) must not crash cleanup."""
    manager, model_path = make_manager(tmp_path)
    stray = tmp_path / "model.preview.jpeg"
    stray.write_bytes(b"data")

    # Must not raise ValueError("Invalid preview filename")
    manager._clean_up_old_previews(str(tmp_path), "model", max_count=1)

    # The unrecognized file is left alone rather than deleted.
    assert stray.exists()


def test_get_existing_image_info_ignores_non_numbered_preview_file(tmp_path):
    manager, model_path = make_manager(tmp_path)
    stray = tmp_path / "model.preview.jpeg"
    stray.write_bytes(b"data")

    # Must not raise ValueError("Invalid preview filename")
    result = manager._get_existing_image_info(str(model_path), str(tmp_path), "model", 1)

    assert result == []


def test_download_images_survives_stray_preview_file(tmp_path):
    """End-to-end: running the metadata-plus-images job style flow with a
    leftover malformed preview file on disk must not raise."""
    manager, model_path = make_manager(tmp_path, max_count=1)
    stray = tmp_path / "model.preview.jpeg"
    stray.write_bytes(b"data")

    metadata = {"images": []}

    # Previously raised ValueError("Invalid preview filename")
    result = manager.download_images(str(model_path), metadata)

    assert result == []

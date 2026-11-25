"""Organization must be idempotent and never re-organize its own output."""

import os
from unittest.mock import MagicMock

import pytest

from civitscraper.jobs.executor import JobExecutor
from civitscraper.organization.config import OrganizationConfig
from civitscraper.organization.organizer import (
    FileOrganizer,
    is_in_organized_output,
    original_dir_for,
)
from civitscraper.scanner.discovery import get_metadata_path

METADATA = {
    "id": 11,
    "modelId": 22,
    "name": "v1",
    "model": {"type": "LORA", "name": "Foo"},
    "images": [{"url": "https://example.invalid/1.jpeg"}],
}


def make_config(tmp_path, mode, recursive=True, output_dir=None):
    models = tmp_path / "loras"
    models.mkdir(exist_ok=True)
    org = {"enabled": True, "template": "by_type", "operation_mode": mode}
    if output_dir:
        org["output_dir"] = output_dir
    config = {
        "api": {"base_url": "https://example.invalid"},
        "input_paths": {"l": {"path": str(models), "type": "LORA", "patterns": ["*.safetensors"]}},
        "jobs": {
            "scan": {
                "type": "scan-paths",
                "paths": ["l"],
                "recursive": recursive,
                "skip_existing": True,
                "organization": org,
                "output": {
                    "metadata": {"html": {"enabled": False}},
                    "images": {"save": False},
                },
            }
        },
    }
    return config, models


def make_executor(config):
    """Executor with a fake API client that counts lookups."""
    api = MagicMock()
    api.get_model_version_by_hash.return_value = dict(METADATA)
    executor = JobExecutor(config, api)
    return executor, api


def run_twice(config):
    executor, api = make_executor(config)
    assert executor.execute_job("scan")
    first_calls = api.get_model_version_by_hash.call_count
    executor2, api2 = make_executor(config)
    assert executor2.execute_job("scan")
    return first_calls, api2.get_model_version_by_hash.call_count


def tree(root):
    return sorted(
        os.path.relpath(os.path.join(d, f), root) for d, _, files in os.walk(root) for f in files
    )


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    # Keep the API disk cache and logs out of the repository
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize("mode", ["copy", "symlink"])
def test_mirror_mode_rerun_makes_no_api_calls_and_no_duplicates(tmp_path, mode):
    config, models = make_config(tmp_path, mode)
    (models / "foo.safetensors").write_bytes(b"x")

    first, second = run_twice(config)

    assert first == 1
    assert second == 0
    # Original got its own sidecar; organized copy has one too; nothing nested.
    files = tree(models)
    assert "foo.json" in files
    assert os.path.join("organized", "LORA", "foo.json") in files
    assert not any(f.count("organized") > 1 for f in files)


def test_move_mode_rerun_does_not_nest(tmp_path):
    config, models = make_config(tmp_path, "move")
    config["jobs"]["scan"]["skip_existing"] = False  # worst case: everything reprocessed
    (models / "foo.safetensors").write_bytes(b"x")

    run_twice(config)

    assert tree(models) == sorted(
        [
            os.path.join("organized", "LORA", "foo.safetensors"),
            os.path.join("organized", "LORA", "foo.json"),
        ]
    )


def test_library_under_folder_named_organized_is_not_mistaken(tmp_path):
    base = tmp_path / "organized" / "loras"
    base.mkdir(parents=True)
    config = {"input_paths": {"l": {"path": str(base), "type": "LORA"}}}
    org = OrganizationConfig(enabled=True, operation_mode="copy")

    assert not is_in_organized_output(str(base / "foo.safetensors"), org, config)
    assert is_in_organized_output(str(base / "organized" / "LORA" / "foo.safetensors"), org, config)


def test_absolute_output_dir_containment(tmp_path):
    out = tmp_path / "sorted"
    org = OrganizationConfig(enabled=True, output_dir=str(out))

    assert is_in_organized_output(str(out / "LORA" / "a.safetensors"), org, {})
    assert not is_in_organized_output(str(tmp_path / "sorted2" / "a.safetensors"), org, {})


def test_original_dir_for_nested_template(tmp_path):
    base = tmp_path / "loras"
    config = {"input_paths": {"l": {"path": str(base), "type": "LORA"}}}
    org = OrganizationConfig(enabled=True, output_dir="{model_dir}/sorted/out")

    organized = base / "sub" / "sorted" / "out" / "LORA" / "creator"
    assert original_dir_for(str(organized), org, config) == str(base / "sub")
    assert original_dir_for(str(base / "sub"), org, config) is None


def test_windows_style_suffix_in_output_dir(tmp_path):
    base = tmp_path / "loras"
    config = {"input_paths": {"l": {"path": str(base), "type": "LORA"}}}
    org = OrganizationConfig(enabled=True, output_dir="{model_dir}\\organized")

    assert is_in_organized_output(str(base / "organized" / "x.safetensors"), org, config)


def test_organize_file_leaves_already_organized_file_in_place(tmp_path):
    config, models = make_config(tmp_path, "move")
    target_dir = models / "organized" / "LORA"
    target_dir.mkdir(parents=True)
    moved = target_dir / "foo.safetensors"
    moved.write_bytes(b"x")
    job_config = JobExecutor.__new__(JobExecutor)
    job_config.config = config
    cfg = job_config._build_job_config(config["jobs"]["scan"])

    result = FileOrganizer(cfg).organize_file(str(moved), METADATA)

    assert result == str(moved)
    assert moved.exists()
    assert get_metadata_path(result, cfg) == str(target_dir / "foo.json")

"""Unknown configuration keys are reported with a suggestion, never rejected."""

import logging
import os

import pytest
import yaml

from civitscraper.config.schema import find_unknown_keys, warn_unknown_keys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_typo_in_job_key_is_reported_with_suggestion():
    """A misspelled job option is found and the right spelling suggested."""
    config = {"jobs": {"scan": {"type": "scan-paths", "skip_exisiting": True}}}

    assert find_unknown_keys(config) == [("jobs.scan.skip_exisiting", "skip_existing")]


def test_job_override_is_checked_against_its_section():
    """A job's output override uses the output schema, not just the job keys."""
    config = {
        "jobs": {
            "scan": {"output": {"metadata": {"html": {"generate_galery": True, "enabled": True}}}}
        }
    }

    assert find_unknown_keys(config) == [
        ("jobs.scan.output.metadata.html.generate_galery", "generate_gallery")
    ]


def test_user_named_maps_and_free_sections_are_accepted():
    """Input path and job names are free, as are preview filename keys."""
    config = {
        "input_paths": {"my loras": {"path": "/x", "type": "LORA", "patterns": ["*.st"]}},
        "output": {"images": {"filenames": {"preview": "{model_name}{ext}", "extra": "x"}}},
        "defaults": {"organization": {"operation_mode": "copy"}},
    }

    assert find_unknown_keys(config) == []


def test_unknown_top_level_section_without_close_match():
    """An unrelated key gets no suggestion."""
    assert find_unknown_keys({"zzz": 1}) == [("zzz", "")]


def test_warn_unknown_keys_logs_one_warning_each(caplog):
    """Each unknown key is one warning; nothing is raised."""
    with caplog.at_level(logging.WARNING, logger="civitscraper.config.schema"):
        count = warn_unknown_keys({"scaner": {}, "api": {"timout": 3}})

    assert count == 2
    messages = [r.getMessage() for r in caplog.records]
    assert "Unknown config key scaner (did you mean scanner?); it is ignored" in messages
    assert "Unknown config key api.timout (did you mean timeout?); it is ignored" in messages


@pytest.mark.parametrize("name", ["default.yaml.example", "default.yaml.minimal"])
def test_shipped_configs_have_no_unknown_keys(name):
    """The example configs only use keys the code reads."""
    with open(os.path.join(REPO, "config", name), encoding="utf-8") as f:
        config = yaml.safe_load(f)

    assert find_unknown_keys(config) == []

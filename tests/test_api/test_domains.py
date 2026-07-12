"""Tests for NSFW detection and civitai.com/civitai.red domain routing."""

import pytest

from civitscraper.api.domains import (
    DEFAULT_DOMAINS,
    build_model_url,
    get_domain_settings,
    is_nsfw,
    model_page_domain,
)


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({"nsfwLevel": 1}, False),   # PG
        ({"nsfwLevel": 2}, False),   # PG-13
        ({"nsfwLevel": 3}, False),   # PG | PG-13, still below Mature
        ({"nsfwLevel": 4}, True),    # Mature
        ({"nsfwLevel": 60}, True),   # Mature|X|XX|XXX
        ({"nsfw": True}, True),      # explicit top-level flag, no level
        ({"nsfw": False}, False),
        ({"model": {"nsfw": True}}, True),   # real by-hash shape: nsfw nested under model
        ({"model": {"nsfw": False}}, False),
        ({"nsfwLevel": 1, "model": {"nsfw": True}}, True),  # nested flag overrides low level
        ({}, False),                 # missing => SFW
    ],
)
def test_is_nsfw(metadata, expected):
    assert is_nsfw(metadata) is expected


def test_is_nsfw_custom_threshold():
    assert is_nsfw({"nsfwLevel": 2}, level_threshold=2) is True
    assert is_nsfw({"nsfwLevel": 4}, level_threshold=8) is False


def test_model_page_domain():
    assert model_page_domain(True, DEFAULT_DOMAINS) == "civitai.red"
    assert model_page_domain(False, DEFAULT_DOMAINS) == "civitai.com"


def test_build_model_url_with_model_id():
    url = build_model_url(123, 456, True, DEFAULT_DOMAINS)
    assert url == "https://civitai.red/models/123?modelVersionId=456"


def test_build_model_url_sfw():
    url = build_model_url(123, 456, False, DEFAULT_DOMAINS)
    assert url == "https://civitai.com/models/123?modelVersionId=456"


def test_build_model_url_without_model_id():
    # Fallback branch mirrors context.py: no /{model_id} segment.
    url = build_model_url(None, 456, True, DEFAULT_DOMAINS)
    assert url == "https://civitai.red/models?modelVersionId=456"


def test_get_domain_settings_defaults():
    domains, threshold, level = get_domain_settings({})
    assert domains == DEFAULT_DOMAINS
    assert threshold == 4
    assert level == "X"


def test_get_domain_settings_partial_override():
    config = {"api": {"domains": {"nsfw": "custom.red"}, "nsfw": {"level_threshold": 8}}}
    domains, threshold, level = get_domain_settings(config)
    assert domains == {"sfw": "civitai.com", "nsfw": "custom.red"}
    assert threshold == 8
    assert level == "X"

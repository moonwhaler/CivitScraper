"""Sidecar bookkeeping: merging refreshed data, removed flags, image identity."""

from civitscraper.scanner.sidecar import (
    DIRTY_FLAG,
    IMAGES_INFO,
    NAMESPACE,
    has_civitai_metadata,
    image_key,
    images_source,
    last_checked,
    last_fetched,
    mark_checked,
    mark_removed,
    merge_refreshed,
)

URL = "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/0a1b2c3d-uuid/original=true/123.jpeg"


def _old():
    return {
        "id": 1,
        "modelId": 2,
        "name": "v1",
        "stats": {"downloadCount": 5},
        "images": [{"url": URL, "meta": {"prompt": "old"}}],
        "parentModel": {"id": 2, "tags": ["style"]},
        "siblingVersions": [{"id": 1}],
        "siblingVersionsFetchedAt": 100.0,
        "activation text": "my trigger",
        "preferred weight": 0.8,
        "notes": "mine",
    }


def test_refresh_keeps_keys_civitai_does_not_send():
    fresh = {
        "id": 1,
        "modelId": 2,
        "name": "v1",
        "stats": {"downloadCount": 9},
        "images": [{"url": URL.replace("0a1b", "ffff"), "meta": {}}],
        IMAGES_INFO: {"source": "showcase", "degraded": False},
    }
    merged = merge_refreshed(_old(), fresh, now=500.0)
    assert merged["stats"] == {"downloadCount": 9}
    assert merged["activation text"] == "my trigger"
    assert merged["preferred weight"] == 0.8 and merged["notes"] == "mine"
    assert merged["parentModel"]["tags"] == ["style"]
    assert merged["siblingVersions"] == [{"id": 1}]
    assert merged["images"] == fresh["images"]
    assert merged[NAMESPACE] == {"fetchedAt": 500.0, "checkedAt": 500.0, "imagesSource": "showcase"}
    assert merged[DIRTY_FLAG] is True and IMAGES_INFO not in merged


def test_degraded_or_empty_images_keep_the_old_list():
    for fresh_images, info in (
        ([{"url": "sfw"}], {"source": "showcase", "degraded": True}),
        ([], {"source": "showcase", "degraded": False}),
    ):
        merged = merge_refreshed(_old(), {"id": 1, "images": fresh_images, IMAGES_INFO: info})
        assert merged["images"] == _old()["images"]


def test_removed_flag_keeps_data_and_first_date():
    flagged = mark_removed(_old(), "version", now=10.0)
    assert {k: v for k, v in flagged.items() if k not in (NAMESPACE, DIRTY_FLAG)} == _old()
    assert flagged[NAMESPACE]["removed"] == {"at": 10.0, "what": "version"}
    widened = mark_removed(flagged, "model", now=20.0)
    assert widened[NAMESPACE]["removed"] == {"at": 10.0, "what": "model"}
    assert widened[NAMESPACE]["checkedAt"] == 20.0
    refreshed = merge_refreshed(widened, {"id": 1, "images": []}, now=30.0)
    assert "removed" not in refreshed[NAMESPACE]


def test_timestamps_fall_back_to_older_stamps(tmp_path):
    assert last_fetched(_old()) == 100.0
    assert last_checked(mark_checked(_old(), now=300.0)) == 300.0
    sidecar = tmp_path / "x.json"
    sidecar.write_text("{}")
    assert last_fetched({}, str(sidecar)) > 0
    assert last_fetched({}) == 0.0


def test_image_identity_and_source():
    assert image_key({"url": URL}) == "0a1b2c3d-uuid"
    assert image_key({"url": URL.replace("original=true", "width=450")}) == "0a1b2c3d-uuid"
    assert image_key({"url": "https://example.com/a/b.png?x=1"}) == "example.com/a/b.png"
    assert image_key({}) == ""
    assert images_source({"images": [{"url": URL}]}) == "showcase"
    assert images_source({"images": [{"id": 5, "url": URL}]}) == "feed"
    assert (
        images_source({NAMESPACE: {"imagesSource": "showcase"}, "images": [{"id": 5}]})
        == "showcase"
    )


def test_forge_only_sidecar_has_no_civitai_metadata():
    assert has_civitai_metadata(_old())
    assert not has_civitai_metadata({"activation text": "x", "description": "mine"})
    assert not has_civitai_metadata(None)

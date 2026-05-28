"""Tests for gallery version merging (ContextBuilder.merge_gallery_models)."""

from civitscraper.html.context import ContextBuilder


def _card(**kwargs):
    """Build a minimal gallery card dict with sensible defaults."""
    card = {
        "name": "Model",
        "model_id": 1,
        "version_id": 100,
        "version": "v1",
        "created_at": "2024-01-01T00:00:00",
        "preview_image_path": "/img/a.png",
        "html_path": "/out/a.html",
        "sibling_versions": [],
    }
    card.update(kwargs)
    return card


def test_two_local_versions_same_model_collapse_to_one_card():
    """Two local versions of one model merge into a single representative card."""
    cards = [
        _card(
            version_id=100, version="v1", created_at="2024-01-01T00:00:00", html_path="/out/v1.html"
        ),
        _card(
            version_id=200, version="v2", created_at="2024-02-01T00:00:00", html_path="/out/v2.html"
        ),
    ]
    merged = ContextBuilder.merge_gallery_models(cards)

    assert len(merged) == 1
    rep = merged[0]
    # Newest (v2) is representative
    assert rep["version_id"] == 200
    versions = rep["versions"]
    assert len(versions) == 2
    assert all(v["is_local"] for v in versions)
    # Newest first
    assert versions[0]["version_id"] == 200
    assert versions[1]["version_id"] == 100


def test_none_model_id_cards_stay_separate():
    """Cards lacking a model_id are never collapsed together."""
    cards = [
        _card(model_id=None, version_id=1, name="A"),
        _card(model_id=None, version_id=2, name="B"),
    ]
    merged = ContextBuilder.merge_gallery_models(cards)
    assert len(merged) == 2
    names = {c["name"] for c in merged}
    assert names == {"A", "B"}


def test_local_plus_remote_only_siblings():
    """Remote-only siblings are added with CivitAI links alongside the local version."""
    siblings = [
        {"id": 100, "name": "v1", "createdAt": "2024-01-01T00:00:00"},
        {"id": 300, "name": "v3", "createdAt": "2024-03-01T00:00:00"},
        {"id": 400, "name": "v4", "createdAt": "2024-04-01T00:00:00"},
    ]
    cards = [
        _card(model_id=5, version_id=100, version="v1", sibling_versions=siblings),
    ]
    merged = ContextBuilder.merge_gallery_models(cards)
    assert len(merged) == 1
    versions = merged[0]["versions"]
    assert len(versions) == 3  # 1 local + 2 remote-only

    local = [v for v in versions if v["is_local"]]
    remote = [v for v in versions if not v["is_local"]]
    assert len(local) == 1
    assert local[0]["version_id"] == 100
    assert len(remote) == 2
    remote_ids = {v["version_id"] for v in remote}
    assert remote_ids == {300, 400}
    for v in remote:
        assert v["link"] == f"https://civitai.com/models/5?modelVersionId={v['version_id']}"


def test_member_created_at_none_does_not_crash():
    """A None created_at must not break representative selection/sorting."""
    cards = [
        _card(version_id=100, version="v1", created_at=None, html_path="/out/v1.html"),
        _card(
            version_id=200, version="v2", created_at="2024-02-01T00:00:00", html_path="/out/v2.html"
        ),
    ]
    merged = ContextBuilder.merge_gallery_models(cards)
    assert len(merged) == 1
    # The one with a real date is "newest"
    assert merged[0]["version_id"] == 200


def test_newest_member_without_preview_falls_back():
    """Representative prefers the newest version that actually has a preview image."""
    cards = [
        # newest but no preview
        _card(
            version_id=200,
            version="v2",
            created_at="2024-02-01T00:00:00",
            preview_image_path=None,
            html_path="/out/v2.html",
        ),
        # older but has preview
        _card(
            version_id=100,
            version="v1",
            created_at="2024-01-01T00:00:00",
            preview_image_path="/img/v1.png",
            html_path="/out/v1.html",
        ),
    ]
    merged = ContextBuilder.merge_gallery_models(cards)
    assert len(merged) == 1
    rep = merged[0]
    # Representative prefers newest WITH preview
    assert rep["version_id"] == 100
    assert rep["preview_image_path"] == "/img/v1.png"


def test_is_current_only_on_representative():
    """Exactly one version is flagged is_current: the representative."""
    cards = [
        _card(
            version_id=100, version="v1", created_at="2024-01-01T00:00:00", html_path="/out/v1.html"
        ),
        _card(
            version_id=200, version="v2", created_at="2024-02-01T00:00:00", html_path="/out/v2.html"
        ),
    ]
    merged = ContextBuilder.merge_gallery_models(cards)
    versions = merged[0]["versions"]
    rep_id = merged[0]["version_id"]
    current = [v for v in versions if v["is_current"]]
    assert len(current) == 1
    assert current[0]["version_id"] == rep_id


def test_remote_dedup_excludes_local_member_ids():
    """A sibling matching a local version id is not duplicated as a remote entry."""
    # sibling list includes the current/local version id 100; must not be double-listed
    siblings = [
        {"id": 100, "name": "v1", "createdAt": "2024-01-01T00:00:00"},
        {"id": 200, "name": "v2", "createdAt": "2024-02-01T00:00:00"},
    ]
    cards = [
        _card(model_id=7, version_id=100, version="v1", sibling_versions=siblings),
    ]
    merged = ContextBuilder.merge_gallery_models(cards)
    versions = merged[0]["versions"]
    ids = [v["version_id"] for v in versions]
    assert ids.count(100) == 1  # not duplicated
    assert sorted(ids) == [100, 200]


def test_no_versions_when_single_version_no_siblings():
    """A lone local version with no siblings yields a single-entry versions list."""
    cards = [_card(model_id=9, version_id=100, sibling_versions=[])]
    merged = ContextBuilder.merge_gallery_models(cards)
    assert len(merged) == 1
    # single local version, no remote -> one entry
    assert len(merged[0]["versions"]) == 1

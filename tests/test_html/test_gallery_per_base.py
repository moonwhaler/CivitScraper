"""One gallery card per CivitAI model and base model, linked as "Also for"."""

import os

from civitscraper.html.context import ContextBuilder


def card(version_id, base, name="Chair", **extra):
    siblings = [
        {"id": 1, "name": "moss v1", "baseModel": "MOSS Image", "createdAt": "2026-01-01"},
        {"id": 2, "name": "krea v1", "baseModel": "Krea 2", "createdAt": "2026-02-01"},
        {"id": 3, "name": "krea v2", "baseModel": "Krea 2", "createdAt": "2026-03-01"},
        {"id": 4, "name": "zit v1", "baseModel": "ZImageTurbo", "createdAt": "2026-04-01"},
        {"id": 5, "name": "pony v1", "baseModel": "Pony", "createdAt": "2026-04-02"},
    ]
    base_card = {"model_id": 9, "version_id": version_id, "version": f"v{version_id}",
                 "base_model": base, "name": name, "html_path": f"/m/{version_id}.html",
                 "file_path": f"/m/{version_id}.safetensors", "created_at": "2026-01-01",
                 "sibling_versions": siblings}
    base_card.update(extra)
    return base_card


def test_two_bases_two_cards_linked_and_updates_per_base():
    cards = ContextBuilder.merge_gallery_models([card(1, "MOSS Image"), card(2, "Krea 2")])
    by_base = {c["base_model"]: c for c in cards}
    assert set(by_base) == {"MOSS Image", "Krea 2"}
    krea = by_base["Krea 2"]
    assert {v["version_id"] for v in krea["versions"]} == {2, 3}  # only its own base
    assert krea["update_version"] == "krea v2"
    assert by_base["MOSS Image"]["update_version"] is None
    assert krea["also_for"] == [{"base": "MOSS Image", "link": "/m/1.html", "local": True}]
    assert "other_bases" not in krea["health"]  # no used bases given: no remote entries


def test_versions_for_used_bases_are_offered_declined_ones_hidden():
    used = {"MOSS Image", "Krea 2", "ZImageTurbo"}  # no Pony folder
    cards = ContextBuilder.merge_gallery_models([card(1, "MOSS Image")], used_bases=used)
    entries = cards[0]["also_for"]
    assert [(e["base"], e["local"]) for e in entries] == [("Krea 2", False), ("ZImageTurbo", False)]
    assert "modelVersionId=3" in entries[0]["link"]  # the newest Krea 2 version
    assert "other_bases" in cards[0]["health"]
    hidden = ContextBuilder.merge_gallery_models(
        [card(1, "MOSS Image")], used_bases=used,
        declined=lambda mid, versions: {v["version_id"] for v in versions if v["version_id"] == 4})
    assert [e["base"] for e in hidden[0]["also_for"]] == ["Krea 2"]


def test_group_path_and_file_size(tmp_path):
    lora = tmp_path / "Lora"
    model = lora / "Krea2" / "style" / "anime" / "x.safetensors"
    inbox = lora / "pre-sort" / "y.safetensors"
    flat = lora / "Krea2" / "z.safetensors"
    for p in (model, inbox, flat):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"12345")
    nested = {"path": str(lora / "Krea2"), "type": "LORA"}
    builder = ContextBuilder({"input_paths": {"inner": nested,
                                              "all": {"path": str(lora), "type": "LORA"}}})
    assert builder.group_path(str(model)) == ["style", "anime"]  # the outermost root wins
    assert builder.group_path(str(flat)) == []
    assert builder.group_path(str(tmp_path / "elsewhere.safetensors")) == []
    assert builder.group_path(str(inbox)) == []  # loose in an inbox: no category
    merged = ContextBuilder.merge_gallery_models(
        [card(1, "Krea 2", file_path=str(model)), card(1, "Krea 2", file_path=str(flat))])
    assert merged[0]["file_size"] == 10  # both copies count
    assert os.path.basename(merged[0]["file_path"]) == "x.safetensors"

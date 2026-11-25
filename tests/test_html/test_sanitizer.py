"""Model descriptions are creator-supplied HTML and must be sanitized."""

from civitscraper.html.renderer import TemplateRenderer
from civitscraper.html.sanitizer import sanitize_description


def test_strips_scripts_handlers_and_js_urls():
    dirty = (
        '<p onclick="steal()">Hi<script>alert(1)</script></p>'
        '<a href="javascript:alert(1)">x</a><img src="data:text/html,evil" onerror="e()">'
        '<iframe src="https://evil.example"></iframe>'
    )
    clean = sanitize_description(dirty)

    for bad in ("<script", "onclick", "onerror", "javascript:", "data:", "<iframe"):
        assert bad not in clean
    assert "<p>Hi</p>" in clean


def test_keeps_formatting_and_safe_links():
    clean = sanitize_description(
        "<h3>Usage</h3><ul><li><strong>weight</strong> 0.8</li></ul>"
        '<a href="https://civitai.com/models/1">model</a>'
    )

    assert "<h3>Usage</h3>" in clean
    assert "<strong>weight</strong>" in clean
    assert 'href="https://civitai.com/models/1"' in clean
    assert 'rel="noopener noreferrer"' in clean


def test_empty_input():
    assert sanitize_description(None) == ""
    assert sanitize_description("") == ""


def test_model_page_never_contains_raw_description_script():
    renderer = TemplateRenderer()
    html = renderer.render_model(
        {
            "title": "t",
            "model_name": "t",
            "description": sanitize_description("<p>ok</p><script>alert('x')</script>"),
            "images": [],
            "images_encoded": "W10=",
            "metadata": {},
            "tags": [],
            "stats": {},
            "sibling_versions": [],
            "parent_model": {},
            "gallery_path": "index.html",
            "model_url": "https://civitai.com",
        }
    )
    assert "alert('x')" not in html
    assert "<p>ok</p>" in html


def test_description_excerpt_is_plain_text_and_bounded():
    from civitscraper.html.sanitizer import description_excerpt

    html = "<p>Use <b>weight</b> 0.8 &amp; trigger <i>foo</i>.</p>" + "<p>word </p>" * 200
    text = description_excerpt(html)

    assert text.startswith("Use weight 0.8 & trigger foo.")
    assert "<" not in text and "&amp;" not in text
    assert len(text) <= 300
    assert not text.endswith(" ")
    assert description_excerpt(None) == ""


def test_merged_gallery_card_drops_raw_sibling_versions():
    from civitscraper.html.context import ContextBuilder

    cards = [
        {"model_id": 1, "version_id": 10, "version": "v1", "sibling_versions": [{"id": 11}]},
        {"model_id": 1, "version_id": 11, "version": "v2", "sibling_versions": [{"id": 10}]},
    ]
    merged = ContextBuilder.merge_gallery_models(cards)

    assert len(merged) == 1
    assert "sibling_versions" not in merged[0]
    assert {v["version_id"] for v in merged[0]["versions"]} == {10, 11}

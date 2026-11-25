"""
Data sanitization utilities for HTML generation.

This module cleans CivitAI's rich-text descriptions before they reach a page.
"""

import html as html_lib
import logging
import re
from typing import Optional

import nh3

logger = logging.getLogger(__name__)


# Markup CivitAI model descriptions actually use (rich-text editor output).
_DESCRIPTION_TAGS = {
    "p",
    "br",
    "hr",
    "span",
    "div",
    "a",
    "b",
    "i",
    "u",
    "s",
    "del",
    "strong",
    "em",
    "sub",
    "sup",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "code",
    "pre",
    "blockquote",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}
_DESCRIPTION_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
}


def sanitize_description(html: Optional[str]) -> str:
    """
    Sanitize a model description (creator-supplied HTML) for safe rendering.

    Scripts, event handlers, styles and non-http(s) URLs (``javascript:``,
    ``data:``) are removed; links get ``rel="noopener noreferrer"``.

    Args:
        html: Raw description HTML from the CivitAI API

    Returns:
        Sanitized HTML ("" for empty input)
    """
    if not html:
        return ""
    return str(
        nh3.clean(
            str(html),
            tags=_DESCRIPTION_TAGS,
            attributes=_DESCRIPTION_ATTRIBUTES,
            url_schemes={"http", "https"},
            link_rel="noopener noreferrer",
        )
    )


def description_excerpt(html: Optional[str], limit: int = 300) -> str:
    """
    Plain-text excerpt of a description for gallery search.

    Tags are stripped, entities decoded and whitespace collapsed; the text is cut
    at a word boundary at most ``limit`` characters long.

    Args:
        html: Raw description HTML
        limit: Maximum excerpt length

    Returns:
        Plain-text excerpt ("" for empty input)
    """
    if not html:
        return ""
    text = nh3.clean(str(html), tags=set())
    text = re.sub(r"\s+", " ", html_lib.unescape(text)).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip()

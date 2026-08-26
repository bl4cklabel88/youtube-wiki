"""Markdown rendering helpers."""
from __future__ import annotations

import re

import markdown as md
import nh3

_MD = md.Markdown(extensions=["extra", "sane_lists", "nl2br", "toc", "tables", "fenced_code"])


def render_markdown(text: str) -> str:
    """Render markdown to HTML and sanitize output to prevent XSS."""
    if not text:
        return ""
    
    # Convert markdown to HTML
    html = _MD.reset().convert(text)
    
    # Sanitize HTML to prevent XSS attacks
    # Allow common safe HTML tags and attributes
    safe_html = nh3.clean(
        html,
        tags={
            "p", "br", "strong", "b", "em", "i", "u", "strike", "del", "ins",
            "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
            "blockquote", "pre", "code", "table", "thead", "tbody", "tr", "td", "th",
            "a", "img", "hr", "div", "span", "sup", "sub"
        },
        attributes={
            "a": {"href", "title"},
            "img": {"src", "alt", "title", "width", "height"},
            "*": {"class", "id"}
        },
        url_schemes={"http", "https", "mailto"}
    )
    
    return safe_html


def strip_markdown(text: str, length: int = 250) -> str:
    """Strip markdown syntax for snippets/excerpts."""
    if not text:
        return ""
    clean = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    clean = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", clean)
    clean = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", clean)
    clean = re.sub(r"[#>*_`~|]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) <= length:
        return clean
    return clean[:length].rstrip() + "…"

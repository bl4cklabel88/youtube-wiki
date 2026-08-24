"""Markdown rendering helpers."""
from __future__ import annotations

import re

import markdown as md

_MD = md.Markdown(extensions=["extra", "sane_lists", "nl2br", "toc", "tables", "fenced_code"])


def render_markdown(text: str) -> str:
    """Render markdown to HTML (cached extension set, safe-ish)."""
    return _MD.reset().convert(text or "")


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

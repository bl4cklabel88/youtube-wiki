"""SQLite FTS5 full-text search over articles."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..database import get_conn, search_articles


@dataclass
class SearchResult:
    id: int
    title: str
    slug: str
    category: Optional[str]
    source_channel: Optional[str]
    source_url: Optional[str]
    snippet: str
    rank: float


def search(query: str, *, category: Optional[str] = None, tag: Optional[str] = None,
           limit: int = 50, offset: int = 0) -> tuple[list[SearchResult], int]:
    """Search the knowledge base. Returns (results, total)."""
    if not query or not query.strip():
        return [], 0
    with get_conn() as conn:
        rows, total = search_articles(conn, query, category=category, tag=tag,
                                      limit=limit, offset=offset)
    results = []
    for r in rows:
        results.append(SearchResult(
            id=r["id"],
            title=r["title"],
            slug=r["slug"],
            category=r["category"],
            source_channel=r["source_channel"],
            source_url=r["source_url"],
            snippet=_make_snippet(r["content_markdown"]),
            rank=float(r["rank"]),
        ))
    return results, total


def _make_snippet(markdown: str, length: int = 220) -> str:
    """Build a plain-text snippet from markdown content."""
    import re

    text = re.sub(r"[#>*`\[\]()\-]", " ", markdown)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= length:
        return text
    return text[:length].rstrip() + "…"

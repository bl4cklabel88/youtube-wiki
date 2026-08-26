from mcp.server.fastmcp import FastMCP
from typing import Any
import json
import logging

from ..database import get_conn, upsert_video
from ..scraper.youtube import extract_video_id
from ..wiki.models import Article
from ..wiki.search import search as wiki_search

logger = logging.getLogger(__name__)

mcp = FastMCP("youtube-wiki", version="0.1.0")

@mcp.tool()
def search_articles(query: str, category: str = None, tags: str = None) -> str:
    """Search the automotive diagnostic wiki knowledge base by keyword."""
    if tags:
        tags = tags.split(",")[0].strip()
    results, total = wiki_search(query, category=category, tag=tags, limit=10)
    return json.dumps({"total": total, "results": [r.__dict__ for r in results]}, default=str)

@mcp.tool()
def get_article(article_id: int) -> str:
    """Fetch a full wiki article by numeric ID."""
    art = Article.get(article_id)
    if not art:
        return json.dumps({"error": f"Article {article_id} not found"})
    return json.dumps({
        "id": art.id, "title": art.title, "slug": art.slug,
        "category": art.category, "source_channel": art.source_channel,
        "source_url": art.source_url, "tags": art.tags,
        "dtc_codes": art.dtc_codes, "vehicle_refs": art.vehicle_refs,
        "tools_used": art.tools_used, "status": art.status,
        "content_markdown": art.content_markdown,
    })

@mcp.tool()
def list_categories() -> str:
    """List all article categories with counts."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS count FROM articles WHERE category IS NOT NULL AND category != '' GROUP BY category ORDER BY count DESC"
        ).fetchall()
    return json.dumps({"categories": [dict(r) for r in rows]})

@mcp.tool()
def list_channels() -> str:
    """List all source channels with video counts."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT channel, COUNT(*) AS count FROM videos GROUP BY channel ORDER BY count DESC"
        ).fetchall()
    return json.dumps({"channels": [dict(r) for r in rows]})

mcp_app = mcp.get_starlette_app()

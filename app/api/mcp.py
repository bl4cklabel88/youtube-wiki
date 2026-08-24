"""MCP server interface exposing the wiki knowledge base as MCP tools.

Mounts a Streamable-HTTP MCP server at /mcp via FastAPI.

Tools:
  - search_articles(query, category?, tags?)
  - get_article(id)
  - submit_video(url)
  - list_categories()
  - list_channels()
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from mcp.server.lowlevel import Server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from ..config import settings
from ..database import get_conn, upsert_video
from ..scraper.youtube import extract_video_id
from ..wiki.models import Article
from ..wiki.search import search as wiki_search

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="search_articles",
        description="Search the automotive diagnostic wiki knowledge base by keyword.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords"},
                "category": {"type": "string", "description": "Filter by category"},
                "tags": {"type": "string", "description": "Comma-separated tag filter"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_article",
        description="Fetch a full wiki article by numeric ID.",
        inputSchema={
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Article ID"}},
            "required": ["id"],
        },
    ),
    Tool(
        name="submit_video",
        description="Submit a YouTube video URL for scraping and processing.",
        inputSchema={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "YouTube video URL or ID"}},
            "required": ["url"],
        },
    ),
    Tool(
        name="list_categories",
        description="List all article categories with counts.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="list_channels",
        description="List all source channels with video counts.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


def _text(obj: Any) -> CallToolResult:
    if isinstance(obj, (dict, list)):
        payload = json.dumps(obj, indent=2, default=str)
    else:
        payload = str(obj)
    return CallToolResult(content=[TextContent(type="text", text=payload)])


def _error(msg: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=msg)], isError=True)


def _handle_tool(name: str, args: dict) -> CallToolResult:
    try:
        if name == "search_articles":
            query = str(args.get("query", "")).strip()
            if not query:
                return _error("query is required")
            category = args.get("category") or None
            tag = args.get("tags") or None
            if tag:
                tag = tag.split(",")[0].strip()
            results, total = wiki_search(query, category=category, tag=tag, limit=50)
            return _text({
                "total": total,
                "results": [r.__dict__ for r in results],
            })

        if name == "get_article":
            aid = int(args.get("id", 0))
            art = Article.get(aid)
            if not art:
                return _error(f"Article {aid} not found")
            return _text({
                "id": art.id, "title": art.title, "slug": art.slug,
                "category": art.category, "source_channel": art.source_channel,
                "source_url": art.source_url, "tags": art.tags,
                "dtc_codes": art.dtc_codes, "vehicle_refs": art.vehicle_refs,
                "tools_used": art.tools_used, "status": art.status,
                "content_markdown": art.content_markdown,
            })

        if name == "submit_video":
            url = str(args.get("url", "")).strip()
            video_id = extract_video_id(url)
            if not video_id:
                return _error(f"Could not extract video ID from {url!r}")
            canonical = f"https://www.youtube.com/watch?v={video_id}"
            with get_conn() as conn:
                row = conn.execute("SELECT * FROM videos WHERE youtube_id = ?", (video_id,)).fetchone()
                if row:
                    if row["status"] not in ("scraped", "processed", "published"):
                        from ..database import enqueue_job
                        enqueue_job(conn, row["id"], "scrape", payload=canonical)
                    return _text({"ok": True, "video_id": video_id, "status": row["status"]})
                vid_row_id = upsert_video(conn, video_id, f"Unknown video {video_id}",
                                          "unknown", canonical, None, status="pending")
                from ..database import enqueue_job
                enqueue_job(conn, vid_row_id, "scrape", payload=canonical)
            return _text({"ok": True, "video_id": video_id, "status": "pending",
                          "message": "Queued for scraping"})

        if name == "list_categories":
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT category, COUNT(*) AS count FROM articles WHERE category IS NOT NULL AND category != '' GROUP BY category ORDER BY count DESC"
                ).fetchall()
            return _text({"categories": [dict(r) for r in rows]})

        if name == "list_channels":
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT channel, COUNT(*) AS count FROM videos GROUP BY channel ORDER BY count DESC"
                ).fetchall()
            return _text({"channels": [dict(r) for r in rows]})

        return _error(f"Unknown tool: {name}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("MCP tool %s failed", name)
        return _error(f"Error in {name}: {exc}")


async def _list_tools(ctx, params) -> ListToolsResult:
    return ListToolsResult(tools=TOOLS)


async def _call_tool(ctx, params) -> CallToolResult:
    name = params.name
    args = params.arguments or {}
    return _handle_tool(name, args)


def create_mcp_server() -> Server:
    """Build the MCP low-level server wired to the wiki."""
    server = Server("youtube-wiki", version="0.1.0",
                    title="YouTube Wiki MCP",
                    description="Automotive diagnostic knowledge base tools")
    server.on_list_tools = _list_tools
    server.on_call_tool = _call_tool
    return server


def get_mcp_app(server: Optional[Server] = None):
    """Return a Starlette app for the MCP server (mounted at /mcp)."""
    server = server or create_mcp_server()
    return server.streamable_http_app(streamable_http_path="/mcp")

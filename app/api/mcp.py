from mcp.server.mcpserver import MCPServer
from mcp.types import Tool, TextContent
from typing import Any
import json
from ..database import get_conn, upsert_video
from ..scraper.youtube import extract_video_id
from ..wiki.models import Article
from ..wiki.search import search as wiki_search

mcp = MCPServer("youtube-wiki", version="0.1.0")

def _text(obj: Any) -> list[TextContent]:
    if isinstance(obj, (dict, list)):
        payload = json.dumps(obj, indent=2, default=str)
    else:
        payload = str(obj)
    return [TextContent(type="text", text=payload)]

def _error(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=msg)]

@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="search_articles", description="Search KB", inputSchema={"type": "object", "properties": {"query": {"type": "string"}}}),
        Tool(name="list_channels", description="List channels", inputSchema={"type": "object", "properties": {}})
    ]

@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "search_articles":
        results, total = wiki_search(arguments.get("query", ""), limit=10)
        return _text({"total": total, "results": [r.__dict__ for r in results]})
    if name == "list_channels":
        with get_conn() as conn:
            rows = conn.execute("SELECT channel, COUNT(*) AS count FROM videos GROUP BY channel").fetchall()
        return _text([dict(r) for r in rows])
    return _error("Unknown tool")

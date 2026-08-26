from mcp.server.lowlevel import Server
from mcp.types import Tool, TextContent, CallToolResult, ListToolsResult
from typing import Any, Optional
import json
import logging

from ..database import get_conn, upsert_video
from ..scraper.youtube import extract_video_id
from ..wiki.models import Article
from ..wiki.search import search as wiki_search

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="search_articles",
        description="Search the automotive diagnostic wiki knowledge base by keyword.",
        inputSchema={"type": "object", "properties": {"query": {"type": "string", "description": "Search keywords"}}, "required": ["query"]},
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

async def _list_tools(*args, **kwargs) -> ListToolsResult:
    return ListToolsResult(tools=TOOLS)

async def _call_tool(ctx, params) -> CallToolResult:
    name = params.name
    args = params.arguments or {}
    try:
        if name == "search_articles":
            results, total = wiki_search(args.get("query", ""), limit=10)
            return _text({"total": total, "results": [r.__dict__ for r in results]})
        if name == "list_channels":
            with get_conn() as conn:
                rows = conn.execute("SELECT channel, COUNT(*) AS count FROM videos GROUP BY channel").fetchall()
            return _text([dict(r) for r in rows])
        return _error("Unknown tool")
    except Exception as exc:
        logger.exception("MCP tool %s failed", name)
        return _error(f"Error: {exc}")

def create_mcp_server() -> Server:
    server = Server("youtube-wiki", version="0.1.0", on_list_tools=_list_tools, on_call_tool=_call_tool)
    return server

def get_mcp_app(server: Optional[Server] = None):
    server = server or create_mcp_server()
    return server.streamable_http_app(streamable_http_path="/sse")

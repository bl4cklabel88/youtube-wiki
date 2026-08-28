from mcp.server import MCPServer
from typing import Any
import json
import logging

from ..services.article_service import (
    search_articles_service,
    get_article_service,
    article_to_dict,
    list_categories_service,
    list_channels_service,
)

logger = logging.getLogger(__name__)

# Create MCP Server
server = MCPServer("youtube-wiki", version="0.1.0")

# Define tool functions using shared services
def search_articles(query: str, category: str = None, tags: str = None) -> str:
    """Search the automotive diagnostic wiki knowledge base by keyword."""
    results, total = search_articles_service(query, category=category, tags=tags, limit=10)
    return json.dumps({"total": total, "results": [article_to_dict(r) for r in results]}, default=str)

def get_article(article_id: int) -> str:
    """Fetch a full wiki article by numeric ID."""
    art = get_article_service(article_id)
    if not art:
        return json.dumps({"error": f"Article {article_id} not found"})
    return json.dumps(article_to_dict(art, include_content=True))

def list_categories() -> str:
    """List all article categories with counts."""
    categories = list_categories_service()
    return json.dumps({"categories": categories})

def list_channels() -> str:
    """List all source channels with video counts."""
    channels = list_channels_service()
    return json.dumps({"channels": channels})

# Add tools to server
server.add_tool(search_articles)
server.add_tool(get_article)
server.add_tool(list_categories)
server.add_tool(list_channels)

# Get the Starlette ASGI app.
# streamable_http_path="/" because the ASGI dispatcher in main.py already
# strips the /mcp prefix before forwarding to this app.  Using the default
# "/mcp" here would cause a path mismatch and make all JSON-RPC endpoints
# (tools/list, tools/call, initialize, etc.) unreachable.
mcp_app = server.streamable_http_app(streamable_http_path="/")

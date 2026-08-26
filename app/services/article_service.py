"""
Shared article service functions to eliminate duplication between REST API and MCP server.
"""

import json
from typing import Dict, List, Optional, Tuple
from ..database import get_conn
from ..wiki.models import Article
from ..wiki.search import search as wiki_search


def search_articles_service(
    query: str, 
    category: str = None, 
    tags: str = None, 
    limit: int = 10,
    offset: int = 0
) -> Tuple[List[Article], int]:
    """
    Search articles with consistent interface for both REST and MCP.
    
    Returns:
        Tuple of (results_list, total_count)
    """
    if tags:
        # Take first tag only for simplicity (as in original MCP code)
        tags = tags.split(",")[0].strip() if tags else None
    
    results, total = wiki_search(query, category=category, tag=tags, limit=limit, offset=offset)
    return results, total


def get_article_service(article_id: int) -> Optional[Article]:
    """
    Get a single article by ID with consistent interface.
    
    Returns:
        Article instance or None if not found
    """
    return Article.get(article_id)


def article_to_dict(article: Article, include_content: bool = True) -> Dict:
    """
    Convert Article to dictionary with consistent field mapping.
    
    Args:
        article: Article instance
        include_content: Whether to include full markdown content
    
    Returns:
        Dictionary representation of article
    """
    result = {
        "id": article.id,
        "title": article.title, 
        "slug": article.slug,
        "category": article.category,
        "source_channel": article.source_channel,
        "source_url": article.source_url,
        "tags": article.tags,
        "dtc_codes": article.dtc_codes,
        "vehicle_refs": article.vehicle_refs,
        "tools_used": article.tools_used,
        "status": article.status,
    }
    
    if include_content:
        result["content_markdown"] = article.content_markdown
        
    # Include timestamps for REST API (optional for MCP)
    if hasattr(article, 'created_at'):
        result["created_at"] = article.created_at
    if hasattr(article, 'updated_at'):
        result["updated_at"] = article.updated_at
        
    return result


def list_categories_service() -> List[Dict]:
    """
    List all categories with article counts.
    
    Returns:
        List of {category, count} dictionaries
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS count FROM articles WHERE category IS NOT NULL AND category != '' GROUP BY category ORDER BY count DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_channels_service() -> List[Dict]:
    """
    List all channels with video counts.
    
    Returns:
        List of {channel, count} dictionaries  
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT channel, COUNT(*) AS count FROM videos GROUP BY channel ORDER BY count DESC"
        ).fetchall()
    return [dict(r) for r in rows]
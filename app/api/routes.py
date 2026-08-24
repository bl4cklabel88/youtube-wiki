"""REST API routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import settings
from ..database import (
    add_source,
    create_article,
    get_article as db_get_article,
    get_conn,
    list_sources,
    remove_source,
    sync_article_to_fts,
    set_article_tags,
    update_article,
)
from ..scraper.youtube import YouTubeScraper, extract_video_id
from ..wiki.models import Article
from ..wiki.search import search as wiki_search

router = APIRouter(prefix="/api", tags=["api"])


def get_scraper() -> YouTubeScraper:
    return YouTubeScraper(
        proxy=settings.socks5_proxy or None,
        rate_limit_seconds=settings.rate_limit_seconds,
        max_retries=settings.max_retries,
    )


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/articles")
def list_articles(
    q: Optional[str] = Query(None, description="Full-text search query"),
    category: Optional[str] = None,
    tag: Optional[str] = None,
    channel: Optional[str] = None,
    status: Optional[str] = Query(None, description="draft or published"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List/search articles. Returns metadata only (no full markdown)."""
    if q and q.strip():
        results, total = wiki_search(q, category=category, tag=tag, limit=limit, offset=offset)
        items = [r.__dict__ for r in results]
        return {"total": total, "limit": limit, "offset": offset, "items": items}
    arts = Article.list(status=status, category=category, channel=channel, tag=tag,
                        limit=limit, offset=offset)
    items = []
    for a in arts:
        items.append({
            "id": a.id, "title": a.title, "slug": a.slug, "category": a.category,
            "source_channel": a.source_channel, "source_url": a.source_url,
            "tags": a.tags, "status": a.status, "updated_at": a.updated_at,
        })
    return {"total": len(items), "limit": limit, "offset": offset, "items": items}


@router.get("/articles/{article_id}")
def get_article_detail(article_id: int):
    art = Article.get(article_id)
    if not art:
        raise HTTPException(404, "Article not found")
    return {
        "id": art.id, "title": art.title, "slug": art.slug,
        "content_markdown": art.content_markdown,
        "category": art.category, "source_channel": art.source_channel,
        "source_url": art.source_url, "dtc_codes": art.dtc_codes,
        "vehicle_refs": art.vehicle_refs, "tools_used": art.tools_used,
        "tags": art.tags, "status": art.status,
        "created_at": art.created_at, "updated_at": art.updated_at,
    }


@router.post("/submit")
def submit_video(url: str = Query(..., description="YouTube video URL/ID")):
    """Submit a video URL for processing (queued asynchronously)."""
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(400, f"Could not extract a YouTube video ID from {url!r}")
    canonical = f"https://www.youtube.com/watch?v={video_id}"

    # Look up existing video row
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM videos WHERE youtube_id = ?", (video_id,)).fetchone()
        if row:
            vid_row_id = row["id"]
            # Enqueue a scrape job if not already processed
            if row["status"] not in ("scraped", "processed", "published"):
                from ..database import enqueue_job
                enqueue_job(conn, vid_row_id, "scrape", payload=canonical)
            return {"ok": True, "video_id": video_id, "status": row["status"],
                    "message": "Video already known; job queued if not processed."}

    # Unknown video: try to fetch metadata synchronously (best-effort)
    scraper = get_scraper()
    meta = scraper.fetch_video_metadata(canonical)
    with get_conn() as conn:
        if meta:
            from ..database import upsert_video, enqueue_job
            vid_row_id = upsert_video(conn, meta.youtube_id, meta.title, meta.channel,
                                      meta.url, meta.duration_seconds, status="pending")
            enqueue_job(conn, vid_row_id, "scrape", payload=meta.url)
            return {"ok": True, "video_id": meta.youtube_id, "status": "pending",
                    "title": meta.title, "message": "Queued for scraping."}
        # Store placeholder + queue anyway
        from ..database import upsert_video, enqueue_job
        vid_row_id = upsert_video(conn, video_id, f"Unknown video {video_id}", "unknown",
                                  canonical, None, status="pending")
        enqueue_job(conn, vid_row_id, "scrape", payload=canonical)
        return {"ok": True, "video_id": video_id, "status": "pending",
                "message": "Metadata lookup failed; queued for scraping anyway."}


@router.get("/channels")
def channels():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT channel, COUNT(*) AS count FROM videos GROUP BY channel ORDER BY count DESC"
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/channels")
def add_channel(url: str = Query(...), name: Optional[str] = None,
                type_: str = Query("channel", pattern="^(channel|playlist|video)$")):
    with get_conn() as conn:
        sid = add_source(conn, url, type_, name, auto_scrape=True)
    return {"ok": True, "id": sid}


@router.delete("/channels/{source_id}")
def delete_channel(source_id: int):
    with get_conn() as conn:
        remove_source(conn, source_id)
    return {"ok": True}


@router.get("/categories")
def categories():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS count FROM articles WHERE category IS NOT NULL AND category != '' GROUP BY category ORDER BY count DESC"
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.get("/tags")
def tags():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT t.name, COUNT(at.article_id) AS count FROM tags t LEFT JOIN article_tags at ON at.tag_id = t.id GROUP BY t.id ORDER BY count DESC"
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.get("/queue")
def queue(status: Optional[str] = None, limit: int = Query(100, le=500)):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT j.*, v.youtube_id, v.title AS video_title, v.channel
               FROM jobs j LEFT JOIN videos v ON v.id = j.video_id
               WHERE (? IS NULL OR j.status = ?)
               ORDER BY j.id DESC LIMIT ?""",
            (status, status, limit),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}

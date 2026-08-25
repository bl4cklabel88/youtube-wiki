"""FastAPI application: REST API + MCP server + Jinja2 wiki UI."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from pathlib import Path
from typing import Optional

import os
from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .api.mcp import create_mcp_server
from mcp.server.sse import SseServerTransport
from .api.routes import router as api_router
from .config import ensure_dirs, settings
from .database import (
    get_conn,
    init_db,
    list_jobs,
    list_sources,
    list_videos,
    remove_source,
)
from .scraper.queue import JobQueue
from .wiki.models import Article, Category, Channel, Tag
from .wiki.render import render_markdown
from .wiki.search import search as wiki_search

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if settings.admin_password == "changeme" or settings.secret_key == "changeme":
    import sys
    logger.critical("CRITICAL SECURITY ERROR: Application is starting with default 'changeme' credentials.")
    logger.critical("Set ADMIN_PASSWORD and SECRET_KEY environment variables to secure values.")
    logger.critical("Refusing to start.")
    sys.exit(1)

ensure_dirs()
init_db()

app = FastAPI(title="YouTube Wiki", version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="youtube_wiki_session",
    max_age=86400 * 7,
)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

# Mount static assets (served from app/static or a symlink to data/)
STATIC_DIR = BASE_DIR / "app" / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# REST API
app.include_router(api_router)

# Setup MCP server routes explicitly
mcp_server = create_mcp_server()
mcp_sse = SseServerTransport("/mcp/messages")

@app.get("/mcp/sse")
async def mcp_handle_sse(request: Request):
    async with mcp_sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp_server.run(streams[0], streams[1], mcp_server.create_initialization_options())

@app.post("/mcp/messages")
async def mcp_handle_messages(request: Request):
    await mcp_sse.handle_post_message(request.scope, request.receive, request._send)

queue = JobQueue()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def is_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(401, "Admin authentication required")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "admin": False})


@app.post("/login")
def login(request: Request, password: str = Form(...), next_url: str = Form("/admin")):
    expected = settings.admin_password
    if not expected or not hmac.compare_digest(password, expected):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"request": request, "admin": False, "error": "Invalid password"},
            status_code=401,
        )
    request.session["admin"] = True
    return RedirectResponse(next_url, status_code=303)


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Templates context
# ---------------------------------------------------------------------------

def _ctx(request: Request, **extra) -> dict:
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_hex(32)
    ctx = {"request": request, "admin": is_admin(request), "csrf_token": request.session["csrf_token"]}
    ctx.update(extra)
    return ctx

def verify_csrf(request: Request, csrf_token: str = Form(...)) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not hmac.compare_digest(csrf_token, expected):
        raise HTTPException(403, "Invalid or missing CSRF token")


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    per_page = 36
    offset = (page - 1) * per_page

    if q and q.strip():
        results, total = wiki_search(q, category=category, tag=tag, limit=per_page, offset=offset)
        articles = []
        for r in results:
            articles.append({
                "id": r.id, "title": r.title, "slug": r.slug, "category": r.category,
                "source_channel": r.source_channel, "source_url": r.source_url,
                "tags": [], "status": "published", "updated_at": "",
                "excerpt": r.snippet,
            })
    else:
        arts = Article.list(status="published", category=category, channel=channel, tag=tag,
                            limit=per_page, offset=offset)
        articles = []
        for a in arts:
            from .wiki.render import strip_markdown
            articles.append({
                "id": a.id, "title": a.title, "slug": a.slug, "category": a.category,
                "source_channel": a.source_channel, "source_url": a.source_url,
                "tags": a.tags, "status": a.status, "updated_at": a.updated_at,
                "excerpt": strip_markdown(a.content_markdown, 260),
            })
        total = len(arts)

    return templates.TemplateResponse(request=request, name="index.html", context=_ctx(request, **{
        "articles": articles,
        "total": total,
        "q": q or "",
        "selected_category": category or "",
        "selected_tag": tag or "",
        "selected_channel": channel or "",
        "categories": Category.list(),
        "channels": Channel.list(),
        "tags": Tag.list(),
        "page": page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }))


@app.get("/article/{slug}", response_class=HTMLResponse)
def article_page(request: Request, slug: str):
    art = Article.get_by_slug(slug)
    if not art:
        raise HTTPException(404, "Article not found")
    html = render_markdown(art.content_markdown)
    return templates.TemplateResponse(request=request, name="article.html", context=_ctx(request, **{
        "article": art,
        "html_content": html,
    }))


# ---------------------------------------------------------------------------
# Admin pages
# ---------------------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    if not is_admin(request):
        return RedirectResponse(f"/login?next_url=/admin", status_code=303)
    with get_conn() as conn:
        sources = [dict(r) for r in list_sources(conn)]
        jobs = [dict(r) for r in list_jobs(conn, limit=100)]
        drafts = [dict(r) for r in conn.execute(
            "SELECT * FROM articles WHERE status = 'draft' ORDER BY updated_at DESC LIMIT 50"
        ).fetchall()]
        videos_stats = dict(conn.execute(
            "SELECT status, COUNT(*) AS n FROM videos GROUP BY status"
        ).fetchall())
    return templates.TemplateResponse(request=request, name="admin.html", context=_ctx(request, **{
        "sources": sources,
        "jobs": jobs,
        "drafts": drafts,
        "video_stats": videos_stats,
        "queue_counts": queue.counts(),
    }))


@app.get("/admin/queue", response_class=HTMLResponse)
def queue_page(request: Request):
    if not is_admin(request):
        return RedirectResponse("/login?next_url=/admin/queue", status_code=303)
    jobs = queue.list(limit=200)
    return templates.TemplateResponse(request=request, name="queue.html", context=_ctx(request, **{
        "jobs": jobs,
        "queue_counts": queue.counts(),
    }))


@app.get("/submit", response_class=HTMLResponse)
def submit_page(request: Request):
    return templates.TemplateResponse(request=request, name="submit.html", context=_ctx(request))


@app.post("/submit", response_class=HTMLResponse)
def submit_form(request: Request, url: str = Form(...), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    from .api.routes import submit_video as _submit_video
    from fastapi.exceptions import HTTPException as HE
    try:
        result = _submit_video(url)
        msg = result.get("message", "Submitted")
        ok = True
    except HE as exc:
        msg = str(exc.detail)
        ok = False
    return templates.TemplateResponse(request=request, name="submit.html", context=_ctx(request, **{
        "submitted": True, "ok": ok, "message": msg, "url": url,
    }))


@app.post("/admin/sources/add")
def admin_add_source(request: Request, url: str = Form(...), type_: str = Form("channel"),
                     name: Optional[str] = Form(None), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    require_admin(request)
    from .database import add_source
    with get_conn() as conn:
        add_source(conn, url, type_, name, auto_scrape=True)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/sources/{source_id}/delete")
def admin_delete_source(request: Request, source_id: int, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    require_admin(request)
    with get_conn() as conn:
        remove_source(conn, source_id)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/jobs/reset-stuck")
def admin_reset_stuck(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    require_admin(request)
    queue.reset_stuck()
    return RedirectResponse("/admin/queue", status_code=303)


@app.post("/admin/articles/{article_id}/publish")
def admin_publish_article(request: Request, article_id: int, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    require_admin(request)
    art = Article.get(article_id)
    if art:
        art.publish()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/articles/{article_id}/unpublish")
def admin_unpublish_article(request: Request, article_id: int, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    require_admin(request)
    art = Article.get(article_id)
    if art:
        art.unpublish()
    return RedirectResponse("/admin", status_code=303)


# ---------------------------------------------------------------------------
# Worker endpoint: claims and runs one queued job (used by cron/systemd timer)
# ---------------------------------------------------------------------------

@app.post("/internal/worker/tick")
def worker_tick(request: Request):
    """Claim and run one queued job. Protected by WORKER_TOKEN via header."""
    token = request.headers.get("X-Worker-Token", "")
    
    # Check WORKER_TOKEN first, fallback to ADMIN_PASSWORD for legacy support
    expected_token = getattr(settings, "worker_token", None)
    if expected_token == "changeme" or not expected_token:
        expected_token = settings.admin_password
        
    if not expected_token or expected_token == "changeme" or not hmac.compare_digest(token, expected_token):
        raise HTTPException(403, "Bad worker token")
        
    job = queue.claim()
    if not job:
        return {"ran": False, "message": "no pending jobs"}
    return {"ran": True, "job": job}

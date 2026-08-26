import os
from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
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
import hmac
import secrets
import logging
from app.scraper.queue import JobQueue
from .wiki.models import Article
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# REST API
app.include_router(api_router)

queue = JobQueue()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def is_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))

def require_admin(request: Request):
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next_url: str = "/admin"):
    if is_admin(request):
        return RedirectResponse(next_url, status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "admin": False, "next_url": next_url})

@app.post("/login")
def login(request: Request, password: str = Form(...), next_url: str = Form("/admin")):
    expected = settings.admin_password
    if not expected or not hmac.compare_digest(password, expected):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"request": request, "admin": False, "error": "Invalid password", "next_url": next_url},
            status_code=401,
        )
    request.session["admin"] = True
    return RedirectResponse(next_url, status_code=303)

@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/", status_code=303)

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
def index(request: Request, q: str = Query(None), category: str = Query(None), tag: str = Query(None)):
    if q or category or tag:
        articles, total = wiki_search(q or "", category=category, tag=tag, limit=100)
    else:
        with get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM articles WHERE status = 'published'").fetchone()[0]
        articles = Article.list(limit=36, offset=0, status="published")

    return templates.TemplateResponse(request=request, name="index.html", context=_ctx(request, **{
        "articles": articles,
        "total": total,
        "q": q or "",
        "selected_category": category or "",
        "selected_tag": tag or "",
    }))


@app.get("/article/{slug}", response_class=HTMLResponse)
def article_detail(request: Request, slug: str):
    art = Article.get_by_slug(slug)
    if not art:
        raise HTTPException(404, "Article not found")
    if art.status != "published" and not is_admin(request):
        raise HTTPException(403, "Not published")

    from .wiki.render import render_markdown
    html = render_markdown(art.content_markdown)

    return templates.TemplateResponse(request=request, name="article.html", context=_ctx(request, **{
        "article": art,
        "html_content": html,
    }))

# ---------------------------------------------------------------------------
# Admin UI
# ---------------------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    require_admin(request)
    with get_conn() as conn:
        sources = list_sources(conn)
        jobs = list_jobs(conn, limit=10)
        videos_stats = conn.execute(
            "SELECT status, COUNT(*) as c FROM videos GROUP BY status ORDER BY c DESC"
        ).fetchall()
        drafts = Article.list(limit=20, status="draft")

    return templates.TemplateResponse(request=request, name="admin.html", context=_ctx(request, **{
        "sources": sources,
        "jobs": jobs,
        "drafts": drafts,
        "video_stats": videos_stats,
        "queue_counts": queue.counts(),
    }))


@app.get("/admin/queue", response_class=HTMLResponse)
def admin_queue(request: Request):
    require_admin(request)
    with get_conn() as conn:
        jobs = list_jobs(conn, limit=100)
    return templates.TemplateResponse(request=request, name="queue.html", context=_ctx(request, **{
        "jobs": jobs,
        "queue_counts": queue.counts(),
    }))


@app.get("/submit", response_class=HTMLResponse)
def submit_page(request: Request):
    return templates.TemplateResponse(request=request, name="submit.html", context=_ctx(request))


@app.post("/submit", response_class=HTMLResponse)
async def submit_form(request: Request, url: str = Form(...), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    from .api.routes import submit_video as _submit_video
    from fastapi.exceptions import HTTPException as HE
    try:
        res = await _submit_video(url)
        ok = res.get("ok")
        msg = res.get("message", "Submitted")
    except HE as e:
        ok = False
        msg = str(e.detail)
    except Exception as e:
        ok = False
        msg = str(e)
    return templates.TemplateResponse(request=request, name="submit.html", context=_ctx(request, **{
        "submitted": True, "ok": ok, "message": msg, "url": url,
    }))


@app.post("/admin/sources/add")
def admin_add_source(request: Request, url: str = Form(...), type_: str = Form("channel"),
                     name: str = Form(None), csrf_token: str = Form(...)):
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


@app.get("/internal/worker/tick")
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


# --- MCP ASGI WRAPPER ---
from .api.mcp import mcp_app
fastapi_app = app

async def asgi_dispatcher(scope, receive, send):
    if scope["type"] == "http" and scope["path"].startswith("/mcp"):
        scope = dict(scope)
        scope["path"] = scope["path"][4:]
        if not scope["path"]:
            scope["path"] = "/"
        return await mcp_app(scope, receive, send)
    return await fastapi_app(scope, receive, send)

app = asgi_dispatcher

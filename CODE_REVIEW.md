# Code Review: YouTube Wiki

## Executive Summary

The YouTube Wiki project is a well-structured, functional application designed to turn YouTube video transcripts into a searchable, structured automotive diagnostic knowledge base using FastAPI, SQLite FTS5, yt-dlp, and OpenAI-compatible LLM APIs.

**Overall Assessment:** **NEEDS WORK (Blocking Security & Production Issues)**

While the architecture and codebase show strong domain modeling and practical design choices (such as FTS5 full-text search, WAL mode SQLite connection management, and MCP server integration), there are **critical security vulnerabilities** and **production readiness gaps** that must be addressed before publishing or deploying:
1. **Unsanitized Markdown Rendering (Stored XSS)** in article pages.
2. **Unauthenticated Channel Management API** (`POST/DELETE /api/channels`).
3. **SSRF Risk in Scraper Pipeline** when accepting raw user-supplied URLs.
4. **Missing CSRF Protection** on admin web form endpoints.
5. **Blocking Synchronous Network I/O** inside HTTP request handlers.
6. **Complete Absence of Automated Tests**.

---

## Critical Issues

### 1. Stored XSS via Unsanitized Markdown Output
- **File:** `app/wiki/render.py` (lines 10-12), `app/templates/article.html` (line 22)
- **Description:** `render_markdown()` converts article Markdown into HTML using `python-markdown` without stripping or sanitizing unsafe raw HTML tags (e.g. `<script>`, `<iframe onload=...>`, `<a href="javascript:...">`). In `article.html`, this HTML is rendered directly via `{{ html_content | safe }}`.
- **Impact:** An attacker who injects malicious HTML into YouTube video transcripts, LLM extractions, or direct article edits can execute arbitrary JavaScript in the browser of any user or admin viewing the article.
- **Remediation:** Pass the output of `convert()` through an HTML sanitizer such as `nh3` or `bleach` before marking it safe:
  ```python
  import nh3

  def render_markdown(text: str) -> str:
      raw_html = _MD.reset().convert(text or "")
      return nh3.clean(raw_html)
  ```

### 2. Missing Authentication on REST API Write Operations
- **File:** `app/api/routes.py` (lines 118-128)
- **Description:** The `/api/channels` (`POST`) and `/api/channels/{source_id}` (`DELETE`) endpoints have no authentication guards or session checks, whereas their admin panel counterparts (`/admin/sources/add`, `/admin/sources/{id}/delete`) require admin auth.
- **Impact:** Any unauthenticated remote user who can reach the API can add arbitrary YouTube channel sources or delete existing sources from the database.
- **Remediation:** Add an authentication dependency (API key or session cookie check) to write routes in `app/api/routes.py`:
  ```python
  @router.post("/channels", dependencies=[Depends(require_api_key)])
  def add_channel(...):
      ...
  ```

### 3. Server-Side Request Forgery (SSRF) / Arbitrary URL Processing in Scraper
- **File:** `app/scraper/youtube.py` (lines 112-188), `app/api/routes.py` (lines 62-101), `app/main.py` (lines 198-205)
- **Description:** The channel and metadata scraper accepts raw URL inputs without validating against a YouTube domain whitelist (`youtube.com`, `youtu.be`). When `yt-dlp` processes arbitrary URLs (or channels), it can attempt network requests to internal IP addresses (e.g., `169.254.169.254`, `127.0.0.1`) or process unsupported URL schemes (`file://`).
- **Impact:** Attackers can submit internal network endpoints or local paths to probe private network infrastructure or elicit server errors.
- **Remediation:** Enforce strict domain and protocol validation on all submitted URLs before passing them to `yt-dlp`:
  ```python
  ALLOWED_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}

  def validate_youtube_url(url: str) -> bool:
      parsed = urllib.parse.urlparse(url)
      return parsed.scheme in ("http", "https") and parsed.netloc.lower() in ALLOWED_DOMAINS
  ```

### 4. Missing CSRF Protection on Admin State-Changing Forms
- **File:** `app/main.py` (lines 198-228)
- **Description:** Admin endpoints (`/admin/sources/add`, `/admin/sources/{id}/delete`, `/admin/jobs/reset-stuck`, `/admin/articles/{id}/publish`, `/admin/articles/{id}/unpublish`) process HTML `POST` forms using cookie-based session auth (`SessionMiddleware`) without checking CSRF tokens.
- **Impact:** A logged-in admin who visits a malicious external site can be tricked into publishing/unpublishing articles, deleting sources, or triggering administrative actions via Cross-Site Request Forgery.
- **Remediation:** Implement anti-CSRF token middleware (or `fastapi-csrf-protect` / same-site cookie strictness + token form fields) for all HTML form submissions.

### 5. Insecure Fallback Secrets and Weak Default Passwords
- **File:** `app/config.py` (lines 42-43)
- **Description:** Default configuration values are hardcoded as `"changeme"` for both `admin_password` and `secret_key`.
- **Impact:** If an operator deploys the application without setting environment variables, session cookies can be forged and admin authentication easily bypassed.
- **Remediation:** Prevent startup if default credentials are detected in non-development environments, or raise a warning at startup:
  ```python
  if settings.secret_key == "changeme" or settings.admin_password == "changeme":
      logger.warning("SECURITY WARNING: Using default admin password or secret key!")
  ```

---

## Important Issues

### 1. Synchronous Blocking I/O in API Request Handlers
- **File:** `app/api/routes.py` (lines 85-93)
- **Description:** When a user submits an unknown video via `POST /api/submit`, the route synchronously invokes `scraper.fetch_video_metadata(canonical)`. `yt-dlp` executes blocking network calls with up to 3 retries and multi-second timeouts inside the main async event loop.
- **Impact:** A single slow YouTube request will block Uvicorn's event loop worker thread, freezing response handling for all other connected users.
- **Remediation:** Offload the metadata fetch to a background thread (`fastapi.concurrency.run_in_threadpool` or `BackgroundTasks`) or enqueue the item immediately as `pending` without doing synchronous scraping during the request.

### 2. Unhandled SQLite FTS5 Syntax Errors in Search
- **File:** `app/database.py` (lines 357-373), `app/wiki/search.py` (lines 20-30)
- **Description:** `_fts_query()` strips single/double quotes and joins terms with `OR`. However, user input containing special FTS operators (e.g., `:`, `NOT`, `AND`, `*`, parentheses) can cause SQLite's FTS5 parser to throw an unhandled `sqlite3.OperationalError`.
- **Impact:** Executing searches with special characters results in an unhandled HTTP 500 error page.
- **Remediation:** Wrap FTS execution in a `try...except sqlite3.OperationalError` block, or escape special characters in user search terms before formatting the query.

### 3. Worker Tick Endpoint Security Design
- **File:** `app/main.py` (lines 236-244)
- **Description:** In `worker_tick`, the route checks `if not settings.admin_password or not hmac.compare_digest(token, settings.admin_password):`. If `admin_password` is set to empty string `""`, `not settings.admin_password` evaluates to `True`, denying access with a 403. Furthermore, reusing `admin_password` as the background worker token forces sharing of superuser credentials with automated cron scripts.
- **Impact:** Confusing authorization failure modes and shared credential risks.
- **Remediation:** Separate `worker_token` into its own distinct configuration parameter (`WORKER_TOKEN`).

### 4. Code Duplication Between REST API and MCP Server
- **File:** `app/api/mcp.py` (lines 60-120), `app/api/routes.py` (lines 62-100)
- **Description:** Video submission logic and database lookup sequences are duplicated verbatim across `app/api/mcp.py` and `app/api/routes.py`.
- **Impact:** Any bug fixes or changes to video ingestion logic must be applied in multiple locations, increasing drift risk.
- **Remediation:** Extract core business logic (such as video submission, source management, and search) into shared service helper functions.

---

## Minor Issues

### 1. Unused Imports in Main Module
- **File:** `app/main.py` (lines 6-8)
- **Description:** `import hashlib` and `import secrets` are imported at the top of `app/main.py` but never referenced in the file.
- **Remediation:** Remove unused imports.

### 2. Dependency List Inconsistencies
- **File:** `requirements.txt`
- **Description:** `requests[socks]>=2.31.0` is listed in `requirements.txt`, but the code uses `httpx` and `yt-dlp`. `requests` is not imported anywhere in the codebase.
- **Remediation:** Remove `requests[socks]` from `requirements.txt` to keep virtualenv dependencies clean.

### 3. Non-Standard Pagination Total Count in Listing Page
- **File:** `app/main.py` (lines 104-124)
- **Description:** In the non-search index view (`q` is empty), `Article.list(...)` is called with `limit=36, offset=...`, and `total = len(arts)` is used to compute page counts.
- **Impact:** `total` will max out at 36, breaking multi-page pagination controls when total articles exceed 36.
- **Remediation:** Implement a separate `Article.count(...)` database query to return the true total count of published articles.

### 4. Logging Configuration Preemption
- **File:** `app/main.py` (line 33)
- **Description:** `logging.basicConfig(level=logging.INFO)` is called directly at module import time in `app/main.py`.
- **Impact:** Calling `basicConfig()` at module level can conflict with Uvicorn's logging setup or custom log formatting in production deployments.
- **Remediation:** Configure logging inside an application lifespan handler or main entrypoint script.

---

## Positive Observations

1. **Clean Database Architecture:** Excellent use of SQLite WAL mode (`PRAGMA journal_mode=WAL`), foreign keys (`PRAGMA foreign_keys=ON`), contextual transaction management (`get_conn()`), and built-in FTS5 full-text indexing.
2. **Robust Fallback Strategy:** The LLM extraction pipeline in `app/processor/extractor.py` gracefully falls back to deterministic heuristic parsing if `LLM_API_KEY` is omitted or if LLM API calls fail, ensuring system operation offline.
3. **Domain-Specific Cleaning:** `app/processor/cleaner.py` features regex fixes tailored to automotive auto-caption errors (e.g. "voltage crop" → "voltage drop", "P 300" → "P0300").
4. **Modern UI and MCP Integration:** Uses Jinja2 + HTMX + Tailwind CSS for a lightweight web UI, paired with a low-level MCP server interface (`app/api/mcp.py`) exposing diagnostic search tools.

---

## Deployment Checklist

Before releasing or pushing this project to production:

- [ ] **Fix XSS Vulnerability:** Integrate `nh3` sanitization in `app/wiki/render.py`.
- [ ] **Secure API Endpoints:** Add authentication guards to `POST /api/channels` and `DELETE /api/channels/{id}`.
- [ ] **Validate URLs (SSRF Protection):** Add YouTube domain and HTTP(S) protocol validation to all submit/scrape routes.
- [ ] **Add CSRF Tokens:** Add CSRF protection to admin forms in `app/main.py` and templates.
- [ ] **Enforce Environment Secrets:** Ensure `ADMIN_PASSWORD` and `SECRET_KEY` are explicitly required in production environment configs.
- [ ] **Catch FTS Query Errors:** Add exception handling around SQLite FTS syntax errors in search handlers.
- [ ] **Make Submit Non-Blocking:** Remove synchronous `yt-dlp` metadata fetching from HTTP request handlers.
- [ ] **Add Automated Tests:** Implement basic unit and integration tests (`pytest`) covering API routes, auth checks, and search rendering.
- [ ] **Clean Up Dependencies:** Remove unused `requests[socks]` from `requirements.txt` and unused imports from `app/main.py`.
- [ ] **Fix Pagination Count:** Implement `Article.count()` to fix total page calculation on the homepage index.

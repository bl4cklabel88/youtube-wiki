## Summary

This PR adds a comprehensive pytest test suite for the youtube-wiki application and fixes several application bugs discovered during testing.

## Test Suite (132 tests, all passing)

### Unit Tests
- **test_database.py** (25 tests): Covers all database operations — videos (upsert, list, update status), sources (add, list, remove, touch, duplicate handling), transcripts (save, retrieve), job queue (enqueue, claim, finish, fail, reset stuck), articles (create, get, update, delete, list with filters), tags (set, update, empty handling), and FTS5 full-text search (query sanitization, search with filters).
- **test_scraper.py** (22 tests): YouTube URL validation, video ID extraction from various URL formats, Shorts detection, scraper initialization, yt-dlp options generation, throttling/rate limiting, metadata fetching (success/failure/retries), channel listing, transcript fetching (success/not available), combined scrape workflow, transcript/model data classes, and file persistence.
- **test_models.py** (12 tests): Article model (from_row, get, get_by_slug, list, save, publish, unpublish), Category/Channel/Tag models, and CSV utility function.
- **test_config.py** (14 tests): Settings defaults, environment variable overrides, path properties, custom paths, caching behavior, ensure_dirs directory creation, and configuration validation.
- **test_processor.py** (10 tests): Processor module imports, workflow structure, and error handling placeholders.

### Integration Tests
- **test_api_routes.py** (25 tests): REST API endpoints — health check, article listing/searching/filtering, article detail, video submission (valid/invalid/existing URLs), channel management (list/add/delete with auth), categories, tags, queue, and metadata endpoints.
- **test_web_routes.py** (24 tests): Web UI routes — public pages (index, search, article detail, submit form), authentication (login success/failure, logout, redirect), admin dashboard/queue, source management, article publishing, worker tick endpoint, and MCP routing.

### Test Infrastructure
- **conftest.py**: Shared fixtures including test database, isolated DB connections, test client, authenticated client, and sample data for videos, articles, and transcripts.
- **pytest.ini**: Strict markers, asyncio mode, verbose output.
- **requirements-dev.txt**: Test dependencies (pytest, pytest-asyncio, httpx, etc.).

## Optimizations (Bug Fixes)

### app/main.py
1. **Missing template variables**: The `index()` view was not passing `pages`, `categories`, `channels`, `selected_channel`, or `page` to the `index.html` template, causing `UndefinedError` crashes. Fixed by fetching and passing all required context.
2. **video_stats format mismatch**: The `admin_dashboard()` view passed a list of sqlite3.Row objects to the template, but `admin.html` calls `.items()` on it (expecting a dict). Fixed by converting the list to a dict before passing to template.

### app/database.py
3. **add_source() duplicate handling bug**: Using `INSERT OR IGNORE` with autocommit returned a stale/wrong `lastrowid` for duplicate inserts. Fixed by checking for existing URL first before inserting, ensuring correct ID is always returned.

### app/wiki/search.py
4. **SearchResult missing tags attribute**: The `SearchResult` dataclass lacked a `tags` attribute that the `index.html` template iterates over (`a.tags[:3]`). Added `tags` field with `__post_init__` defaulting to empty list.

## Testing
All 132 tests pass with 1 skipped (processor placeholder):

```
======================== 132 passed, 1 skipped in 6.70s ========================
```

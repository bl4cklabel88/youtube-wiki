"""SQLite database layer: schema initialization, connections, and all SQL.

Uses WAL mode for concurrent reads during scraping. FTS5 is used for
full-text search (built into modern SQLite builds).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from .config import settings

SCHEMA_SQL = """
-- Videos
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    youtube_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    channel TEXT NOT NULL,
    url TEXT NOT NULL,
    duration_seconds INTEGER,
    status TEXT DEFAULT 'pending',  -- pending, scraped, processing, published, failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Channels/Playlists (subscriptions)
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    type TEXT NOT NULL,  -- channel, playlist, video
    name TEXT,
    last_scraped_at TIMESTAMP,
    auto_scrape BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Articles
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    video_id INTEGER REFERENCES videos(id),
    title TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    content_markdown TEXT NOT NULL,
    category TEXT,
    source_channel TEXT,
    source_url TEXT,
    dtc_codes TEXT,        -- comma-separated
    vehicle_refs TEXT,     -- comma-separated
    tools_used TEXT,       -- comma-separated
    status TEXT DEFAULT 'draft',  -- draft, published
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tags
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS article_tags (
    article_id INTEGER REFERENCES articles(id),
    tag_id INTEGER REFERENCES tags(id),
    PRIMARY KEY (article_id, tag_id)
);

-- Raw transcripts
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY,
    video_id INTEGER REFERENCES videos(id),
    raw_text TEXT NOT NULL,
    segments_json TEXT NOT NULL,
    language TEXT DEFAULT 'en',
    is_auto_generated BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Job queue
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    video_id INTEGER REFERENCES videos(id),
    job_type TEXT NOT NULL DEFAULT 'scrape',  -- scrape, process
    status TEXT NOT NULL DEFAULT 'pending',   -- pending, running, done, failed
    attempts INTEGER DEFAULT 0,
    error TEXT,
    payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
"""

# FTS5 virtual table (must be created after the content table exists)
FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title, content_markdown, category, tags
    
);
"""


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a SQLite connection with sane defaults (WAL, foreign keys)."""
    path = db_path or settings.database_path
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


@contextmanager
def get_conn(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Context manager yielding a connection, committing on success."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Create all tables (idempotent)."""
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(FTS_SQL)


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------

UPSERT_VIDEO_SQL = """
INSERT INTO videos (youtube_id, title, channel, url, duration_seconds, status, updated_at)
VALUES (:youtube_id, :title, :channel, :url, :duration_seconds, :status, CURRENT_TIMESTAMP)
ON CONFLICT(youtube_id) DO UPDATE SET
    title = excluded.title,
    channel = excluded.channel,
    url = excluded.url,
    duration_seconds = COALESCE(excluded.duration_seconds, videos.duration_seconds),
    updated_at = CURRENT_TIMESTAMP
"""


def upsert_video(conn: sqlite3.Connection, youtube_id: str, title: str, channel: str,
                 url: str, duration_seconds: Optional[int] = None,
                 status: str = "pending") -> int:
    """Insert or update a video row, returning its id."""
    cur = conn.execute(UPSERT_VIDEO_SQL, {
        "youtube_id": youtube_id, "title": title, "channel": channel,
        "url": url, "duration_seconds": duration_seconds, "status": status,
    })
    row = conn.execute("SELECT id FROM videos WHERE youtube_id = ?", (youtube_id,)).fetchone()
    return row["id"]


def get_video_by_youtube_id(conn: sqlite3.Connection, youtube_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM videos WHERE youtube_id = ?", (youtube_id,)).fetchone()


def get_video(conn: sqlite3.Connection, video_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()


def list_videos(conn: sqlite3.Connection, status: Optional[str] = None,
                channel: Optional[str] = None, limit: int = 500, offset: int = 0) -> list[sqlite3.Row]:
    q = "SELECT * FROM videos WHERE 1=1"
    params: list = []
    if status:
        q += " AND status = ?"
        params.append(status)
    if channel:
        q += " AND channel LIKE ?"
        params.append(f"%{channel}%")
    q += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return conn.execute(q, params).fetchall()


def update_video_status(conn: sqlite3.Connection, video_id: int, status: str) -> None:
    conn.execute(
        "UPDATE videos SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, video_id),
    )


# ---------------------------------------------------------------------------
# Sources (channels / playlists / videos)
# ---------------------------------------------------------------------------

def add_source(conn: sqlite3.Connection, url: str, type_: str, name: Optional[str] = None,
               auto_scrape: bool = False) -> int:
    existing = conn.execute("SELECT id FROM sources WHERE url = ?", (url,)).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO sources (url, type, name, auto_scrape) VALUES (?, ?, ?, ?)",
        (url, type_, name, int(auto_scrape)),
    )
    return cur.lastrowid


def list_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM sources ORDER BY created_at DESC").fetchall()


def remove_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))


def touch_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("UPDATE sources SET last_scraped_at = CURRENT_TIMESTAMP WHERE id = ?", (source_id,))


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------

def save_transcript(conn: sqlite3.Connection, video_id: int, raw_text: str,
                    segments: list, language: str = "en",
                    is_auto_generated: bool = True) -> int:
    cur = conn.execute(
        """INSERT INTO transcripts (video_id, raw_text, segments_json, language, is_auto_generated)
           VALUES (?, ?, ?, ?, ?)""",
        (video_id, raw_text, json.dumps(segments), language, int(is_auto_generated)),
    )
    return cur.lastrowid


def get_transcript_for_video(conn: sqlite3.Connection, video_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM transcripts WHERE video_id = ? ORDER BY id DESC LIMIT 1", (video_id,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Jobs (queue)
# ---------------------------------------------------------------------------

def enqueue_job(conn: sqlite3.Connection, video_id: int, job_type: str = "scrape",
                payload: Optional[str] = None) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (video_id, job_type, status, payload) VALUES (?, ?, 'pending', ?)",
        (video_id, job_type, payload),
    )
    return cur.lastrowid


def claim_next_job(conn: sqlite3.Connection, job_type: Optional[str] = None) -> Optional[sqlite3.Row]:
    q = "SELECT * FROM jobs WHERE status = 'pending'"
    params: list = []
    if job_type:
        q += " AND job_type = ?"
        params.append(job_type)
    q += " ORDER BY id ASC LIMIT 1"
    row = conn.execute(q, params).fetchone()
    if row:
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )
        return row
    return None


def finish_job(conn: sqlite3.Connection, job_id: int, status: str, error: Optional[str] = None) -> None:
    conn.execute(
        "UPDATE jobs SET status = ?, error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, error, job_id),
    )


def fail_job(conn: sqlite3.Connection, job_id: int, error: str) -> None:
    finish_job(conn, job_id, "failed", error)


def list_jobs(conn: sqlite3.Connection, status: Optional[str] = None, limit: int = 100) -> list[sqlite3.Row]:
    q = """SELECT j.*, v.youtube_id, v.title AS video_title, v.channel
           FROM jobs j LEFT JOIN videos v ON v.id = j.video_id WHERE 1=1"""
    params: list = []
    if status:
        q += " AND j.status = ?"
        params.append(status)
    q += " ORDER BY j.id DESC LIMIT ?"
    params.append(limit)
    return conn.execute(q, params).fetchall()


def reset_stuck_jobs(conn: sqlite3.Connection) -> int:
    """Reset jobs stuck in 'running' back to 'pending' (e.g. after crash)."""
    cur = conn.execute("UPDATE jobs SET status = 'pending' WHERE status = 'running'")
    return cur.rowcount


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------

def create_article(conn: sqlite3.Connection, *, video_id: Optional[int], title: str, slug: str,
                   content_markdown: str, category: Optional[str] = None,
                   source_channel: Optional[str] = None, source_url: Optional[str] = None,
                   dtc_codes: Optional[str] = None, vehicle_refs: Optional[str] = None,
                   tools_used: Optional[str] = None, status: str = "draft") -> int:
    cur = conn.execute(
        """INSERT INTO articles (video_id, title, slug, content_markdown, category,
                                 source_channel, source_url, dtc_codes, vehicle_refs,
                                 tools_used, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, title, slug, content_markdown, category, source_channel, source_url,
         dtc_codes, vehicle_refs, tools_used, status),
    )
    return cur.lastrowid


def get_article(conn: sqlite3.Connection, article_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()


def get_article_by_slug(conn: sqlite3.Connection, slug: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM articles WHERE slug = ?", (slug,)).fetchone()


def list_articles(conn: sqlite3.Connection, *, status: Optional[str] = None,
                  category: Optional[str] = None, channel: Optional[str] = None,
                  tag: Optional[str] = None, limit: int = 100, offset: int = 0) -> list[sqlite3.Row]:
    q = """SELECT DISTINCT a.* FROM articles a"""
    params: list = []
    if tag:
        q += """ JOIN article_tags at ON at.article_id = a.id
                 JOIN tags t ON t.id = at.tag_id AND t.name = ?"""
        params.append(tag)
    q += " WHERE 1=1"
    if status:
        q += " AND a.status = ?"
        params.append(status)
    if category:
        q += " AND a.category = ?"
        params.append(category)
    if channel:
        q += " AND a.source_channel LIKE ?"
        params.append(f"%{channel}%")
    q += " ORDER BY a.updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return conn.execute(q, params).fetchall()


def update_article(conn: sqlite3.Connection, article_id: int, **fields) -> None:
    allowed = {"title", "slug", "content_markdown", "category", "source_channel",
               "source_url", "dtc_codes", "vehicle_refs", "tools_used", "status"}
    sets = [f"{k} = ?" for k in fields if k in allowed]
    if not sets:
        return
    vals = [fields[k] for k in fields if k in allowed]
    vals.append(article_id)
    conn.execute(
        f"UPDATE articles SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        vals,
    )


def set_article_status(conn: sqlite3.Connection, article_id: int, status: str) -> None:
    conn.execute("UPDATE articles SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                 (status, article_id))


def delete_article(conn: sqlite3.Connection, article_id: int) -> None:
    conn.execute("DELETE FROM article_tags WHERE article_id = ?", (article_id,))
    conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))


def list_categories(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT category, COUNT(*) AS count FROM articles WHERE category IS NOT NULL AND category != '' GROUP BY category ORDER BY count DESC"
    ).fetchall()


def list_channels(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT channel, COUNT(*) AS count FROM videos GROUP BY channel ORDER BY count DESC"
    ).fetchall()


def list_tags(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT t.name, COUNT(at.article_id) AS count FROM tags t LEFT JOIN article_tags at ON at.tag_id = t.id GROUP BY t.id ORDER BY count DESC"
    ).fetchall()


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def set_article_tags(conn: sqlite3.Connection, article_id: int, tags: list[str]) -> None:
    conn.execute("DELETE FROM article_tags WHERE article_id = ?", (article_id,))
    for name in tags:
        name = name.strip()
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO article_tags (article_id, tag_id) VALUES (?, ?)",
                (article_id, row["id"]),
            )


def get_article_tags(conn: sqlite3.Connection, article_id: int) -> list[str]:
    rows = conn.execute(
        """SELECT t.name FROM tags t
           JOIN article_tags at ON at.tag_id = t.id
           WHERE at.article_id = ? ORDER BY t.name""",
        (article_id,),
    ).fetchall()
    return [r["name"] for r in rows]


# ---------------------------------------------------------------------------
# FTS5 search
# ---------------------------------------------------------------------------

def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS index from scratch (call after bulk inserts)."""
    conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild');")


def sync_article_to_fts(conn: sqlite3.Connection, article_id: int) -> None:
    """Sync a single article into the FTS index (external-content table)."""
    conn.execute("DELETE FROM articles_fts WHERE rowid = ?", (article_id,))
    row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        return
    tags = ",".join(get_article_tags(conn, article_id))
    conn.execute(
        """INSERT INTO articles_fts(rowid, title, content_markdown, category, tags)
           VALUES (?, ?, ?, ?, ?)""",
        (article_id, row["title"], row["content_markdown"], row["category"] or "", tags),
    )


def search_articles(conn: sqlite3.Connection, query: str, *, category: Optional[str] = None,
                    tag: Optional[str] = None, limit: int = 50, offset: int = 0) -> tuple[list[sqlite3.Row], int]:
    """Full-text search over articles using FTS5. Returns (rows, total_count)."""
    q = """SELECT a.*, bm25(articles_fts) AS rank FROM articles_fts
           JOIN articles a ON a.id = articles_fts.rowid
           WHERE articles_fts MATCH ?"""
    params: list = [_fts_query(query)]
    if category:
        q += " AND a.category = ?"
        params.append(category)
    if tag:
        q += """ AND a.id IN (SELECT article_id FROM article_tags at JOIN tags t ON t.id = at.tag_id WHERE t.name = ?)"""
        params.append(tag)
    q += " ORDER BY rank LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(q, params).fetchall()

    count_q = """SELECT COUNT(*) AS total FROM articles_fts
                 JOIN articles a ON a.id = articles_fts.rowid
                 WHERE articles_fts MATCH ?"""
    count_params: list = [_fts_query(query)]
    if category:
        count_q += " AND a.category = ?"
        count_params.append(category)
    if tag:
        count_q += """ AND a.id IN (SELECT article_id FROM article_tags at JOIN tags t ON t.id = at.tag_id WHERE t.name = ?)"""
        count_params.append(tag)
    total = conn.execute(count_q, count_params).fetchone()["total"]
    return rows, total


def _fts_query(raw: str) -> str:
    """Build a safe FTS5 MATCH expression from user input."""
    import re
    # Strip everything except alphanumeric, spaces, and hyphens to prevent FTS5 syntax errors
    clean = re.sub(r'[^a-zA-Z0-9\-\s]', '', raw)
    terms = clean.split()
    if not terms:
        return "*"
    return " OR ".join(f'"{t}"*' for t in terms)

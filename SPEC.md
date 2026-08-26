# YouTube Wiki — Automotive Diagnostic Knowledge Base

## Overview
A self-hosted service that scrapes YouTube transcripts from curated automotive diagnostic channels, processes them into structured knowledge base articles, and serves them as a searchable wiki with an admin panel for managing video submissions.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Admin Panel (Web UI)                   │
│  - Submit new YouTube URL for transcription              │
│  - Manage channels/playlists (add/remove)                 │
│  - Review and edit generated articles                     │
│  - Tag/categorize articles                                │
│  - View scraping queue status                             │
├─────────────────────────────────────────────────────────┤
│                    API Server (FastAPI)                   │
│  REST API + MCP server interface                          │
├─────────────┬──────────────┬─────────────────────────────┤
│  Scraper    │  Processor   │  Wiki Service               │
│  (yt-dlp +  │  (LLM cleanup│  (Article storage,          │
│   transcript│   + structure │   search, render)            │
│   API)      │   extraction) │                             │
├─────────────┴──────────────┴─────────────────────────────┤
│              Storage Layer                                │
│  SQLite/PostgreSQL + File system (markdown articles)     │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. Scraper Pipeline
- **yt-dlp** with SOCKS5 proxy for video metadata + auto-subtitle download
- **youtube-transcript-api** with SOCKS5 proxy as fallback/alternative for clean text
- Inputs: YouTube channel URL, playlist URL, or individual video URL
- Outputs: Raw transcript JSON (timestamp + text segments), video metadata
- Proxy config: `socks5h://user:pass@host:port` (env var `SOCKS5_PROXY`)
- Rate limiting: configurable delay between requests (default 2-5 seconds)
- Retry logic: exponential backoff on failures
- Queue: SQLite-backed job queue for batch processing

### 2. Transcript Processor
- Raw transcript → clean text (remove VTT formatting, timing artifacts)
- LLM cleanup pass: fix technical automotive terminology errors
  - "voltage crop" → "voltage drop"
  - "P 300" → "P0300"
  - "oscilla scope" → "oscilloscope"
  - etc.
- LLM extraction pass: convert transcript into structured article
  - Title, technique name, when to use, method steps, key insights, common mistakes
  - Tag with categories (electrical, engine, transmission, methodology, etc.)
  - Extract vehicle references (make/model/year when mentioned)
  - Extract DTC codes mentioned
  - Extract tools/equipment used
- Output: Markdown article files + metadata JSON

### 3. Knowledge Base / Wiki
- Self-hosted wiki with:
  - Article listing with filtering by category, tags, source channel
  - Full-text search across all articles
  - Article pages with rendered markdown, source video embed/link
  - Public read access, admin write access
- Storage: Markdown files on filesystem + SQLite metadata index
- Search: SQLite FTS5 (full-text search) — no external search server needed

### 4. Admin Panel
- Web UI for:
  - Submitting new YouTube URLs (video/playlist/channel) for processing
  - Viewing scraping queue and job status
  - Editing/reviewing generated articles before publishing
  - Managing channel/playlist subscriptions
  - Bulk re-processing of articles
- Authentication: simple admin password (env var `ADMIN_PASSWORD`)

### 5. API / MCP Server
- REST API for programmatic access:
  - `GET /api/articles` — list/search articles
  - `GET /api/articles/{id}` — get full article
  - `POST /api/submit` — submit new video URL for processing
  - `GET /api/channels` — list managed channels
  - `POST /api/channels` — add channel to scrape
- MCP server interface (separate endpoint):
  - `search_articles(query, category?, tags?)` — search knowledge base
  - `get_article(id)` — fetch full article
  - `submit_video(url)` — submit new video for processing
  - `list_categories()` — list available categories
  - `list_channels()` — list managed channels

## Tech Stack
- **Language:** Python 3.11+
- **Web Framework:** FastAPI + Uvicorn
- **Database:** SQLite (with WAL mode for concurrency)
- **Full-Text Search:** SQLite FTS5
- **Frontend:** Server-rendered Jinja2 templates + HTMX + Tailwind CSS (via CDN)
- **YouTube Scraping:** yt-dlp + youtube-transcript-api
- **Transcript Processing:** OpenAI-compatible API (configurable endpoint)
- **Process Management:** systemd service
- **Reverse Proxy:** Nginx (on production VPS)

## Configuration (Environment Variables)
```
# Proxy
SOCKS5_PROXY=socks5h://user:pass@host:port

# LLM Processing (OpenAI-compatible)
LLM_API_BASE=https://api.openai.com/v1  # or local endpoint
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini  # or any compatible model

# Database
DATABASE_PATH=./data/wiki.db

# Storage
ARTICLES_DIR=./data/articles
TRANSCRIPTS_DIR=./data/transcripts

# Admin
ADMIN_PASSWORD=changeme
SECRET_KEY=changeme

# Server
HOST=0.0.0.0
PORT=8000

# Scraping
RATE_LIMIT_SECONDS=3
MAX_RETRIES=3
```

## Directory Structure
```
youtube-wiki/
├── README.md
├── SPEC.md
├── requirements.txt
├── .env.example
├── data/
│   ├── scannerdanner_all.txt       # Pre-seeded video lists
│   ├── aft_filtered.txt
│   ├── playlist_motorage.txt
│   ├── wiki.db                      # SQLite database
│   ├── articles/                    # Generated markdown articles
│   └── transcripts/                 # Raw transcript JSON
├── app/
│   ├── __init__.py
│   ├── main.py                      # FastAPI app
│   ├── config.py                    # Settings from env
│   ├── database.py                  # SQLite models + FTS
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── youtube.py               # yt-dlp + transcript-api wrapper
│   │   ├── queue.py                 # Job queue management
│   │   └── channels.py              # Channel/playlist management
│   ├── processor/
│   │   ├── __init__.py
│   │   ├── cleaner.py                # Transcript cleanup
│   │   ├── extractor.py              # LLM extraction → structured article
│   │   └── prompts.py               # LLM prompt templates
│   ├── wiki/
│   │   ├── __init__.py
│   │   ├── models.py                # Article, Category, Tag models
│   │   ├── search.py                # FTS5 search
│   │   └── render.py                # Markdown rendering
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py                # REST API routes
│   │   └── mcp.py                   # MCP server interface
│   └── templates/                   # Jinja2 templates
│       ├── base.html
│       ├── index.html               # Article listing
│       ├── article.html             # Single article view
│       ├── admin.html                # Admin panel
│       ├── submit.html               # Submit new video
│       └── queue.html                # Job queue view
├── scripts/
│   ├── init_db.py                   # Initialize database
│   ├── scrape_channel.py            # CLI: scrape a channel
│   ├── scrape_playlist.py           # CLI: scrape a playlist
│   ├── scrape_video.py              # CLI: scrape single video
│   ├── process_transcripts.py       # CLI: process raw transcripts
│   └── seed_data.py                 # Load pre-seeded video lists
├── systemd/
│   └── youtube-wiki.service         # systemd service file
└── nginx/
    └── youtube-wiki.conf            # Nginx config example
```

## Database Schema

```sql
-- Videos
CREATE TABLE videos (
    id INTEGER PRIMARY KEY,
    youtube_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    channel TEXT NOT NULL,
    url TEXT NOT NULL,
    duration_seconds INTEGER,
    status TEXT DEFAULT 'pending',  -- pending, scraped, processed, published, failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Channels/Playlists (subscriptions)
CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    type TEXT NOT NULL,  -- channel, playlist, video
    name TEXT,
    last_scraped_at TIMESTAMP,
    auto_scrape BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Articles
CREATE TABLE articles (
    id INTEGER PRIMARY KEY,
    video_id INTEGER REFERENCES videos(id),
    title TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    content_markdown TEXT NOT NULL,
    category TEXT,
    source_channel TEXT,
    source_url TEXT,
    dtc_codes TEXT,        -- comma-separated
    vehicle_refs TEXT,      -- comma-separated
    tools_used TEXT,       -- comma-separated
    status TEXT DEFAULT 'draft',  -- draft, published
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tags
CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE article_tags (
    article_id INTEGER REFERENCES articles(id),
    tag_id INTEGER REFERENCES tags(id),
    PRIMARY KEY (article_id, tag_id)
);

-- Full-text search
CREATE VIRTUAL TABLE articles_fts USING fts5(
    title, content_markdown, category, tags,
    content='articles', content_rowid='id'
);

-- Raw transcripts
CREATE TABLE transcripts (
    id INTEGER PRIMARY KEY,
    video_id INTEGER REFERENCES videos(id),
    raw_text TEXT NOT NULL,
    segments_json TEXT NOT NULL,
    language TEXT DEFAULT 'en',
    is_auto_generated BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Deployment (VPS)

### Prerequisites
- Python 3.11+
- Nginx
- systemd

### Install
```bash
git clone https://github.com/bl4cklabel88/youtube-wiki.git /opt/youtube-wiki
cd /opt/youtube-wiki
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your config
```

### Initialize
```bash
python scripts/init_db.py
python scripts/seed_data.py  # Load pre-seeded video lists
```

### Scrape (first run)
```bash
# Scrape all ScannerDanner videos (non-shorts)
python scripts/scrape_channel.py --channel "@ScannerDanner" --filter-shorts

# Scrape AFT (non-podcast, non-shorts)
python scripts/scrape_channel.py --channel "@AutomotiveFieldTheory" --filter-podcast --filter-shorts

# Scrape playlist
python scripts/scrape_playlist.py --playlist "PLjzZLCfQx8TsHaJMsBYPvOqwhA-XuPa7l"
```

### Process (convert transcripts to articles)
```bash
# Process all scraped transcripts
python scripts/process_transcripts.py --all

# Or process specific video
python scripts/process_transcripts.py --video-id 98lyvpPonxQ
```

### Run server
```bash
# Development
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Production (systemd)
sudo cp systemd/youtube-wiki.service /etc/systemd/system/
sudo systemctl enable youtube-wiki
sudo systemctl start youtube-wiki

# Nginx
sudo cp nginx/youtube-wiki.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/youtube-wiki.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## MCP Server Integration
The MCP server runs as a separate process or endpoint alongside the REST API:

```json
{
  "mcpServers": {
    "youtube-wiki": {
      "url": "http://localhost:8000/mcp",
      "enabled": true
    }
  }
}
```

Tools exposed:
- `search_articles(query, category?, tags?)` — search knowledge base
- `get_article(id)` — fetch full article
- `submit_video(url)` — submit new video for processing
- `list_categories()` — list available categories
- `list_channels()` — list managed channels
```

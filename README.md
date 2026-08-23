# youtube-wiki

Self-hosted automotive diagnostic knowledge base built from YouTube transcripts.

## What it does
- Scrapes transcripts from curated YouTube automotive diagnostic channels
- Processes raw transcripts into structured, searchable wiki articles using LLM
- Serves a public wiki with full-text search + admin panel for content management
- Exposes REST API and MCP server for agent integration

## Quick Start
```bash
git clone https://github.com/bl4cklabel88/youtube-wiki.git
cd youtube-wiki
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your config
python scripts/init_db.py
python scripts/seed_data.py
uvicorn app.main:app --reload
```

See [SPEC.md](SPEC.md) for full architecture and deployment docs.

## Tech Stack
- Python 3.11+, FastAPI, SQLite (FTS5), Jinja2 + HTMX + Tailwind
- yt-dlp + youtube-transcript-api (with SOCKS5 proxy)
- OpenAI-compatible LLM for transcript processing

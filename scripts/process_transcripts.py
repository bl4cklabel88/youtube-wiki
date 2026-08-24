#!/usr/bin/env python3
"""Process scraped transcripts into structured wiki articles.

Usage:
    python scripts/process_transcripts.py --all
    python scripts/process_transcripts.py --video-id 98lyvpPonxQ
    python scripts/process_transcripts.py --status scraped --limit 10
    python scripts/process_transcripts.py --all --force
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import (  # noqa: E402
    create_article,
    get_article_by_slug,
    get_conn,
    get_transcript_for_video,
    get_video,
    init_db,
    set_article_status,
    set_article_tags,
    sync_article_to_fts,
    update_article,
    update_video_status,
)
from app.processor.cleaner import clean_transcript, join_segments  # noqa: E402
from app.processor.extractor import LLMExtractor, slugify  # noqa: E402

logger = logging.getLogger(__name__)


def process_one(conn, video: dict, extractor: LLMExtractor, *, force: bool = False,
                publish: bool = False) -> str:
    """Process a single video's transcript into an article. Returns status string."""
    video_id = video["id"]
    tx = get_transcript_for_video(conn, video_id)
    if not tx:
        logger.info("Video %s has no transcript; skipping.", video["youtube_id"])
        return "no-transcript"

    # Already processed?
    existing = conn.execute(
        "SELECT id FROM articles WHERE video_id = ?", (video_id,)
    ).fetchone()
    if existing and not force:
        logger.info("Video %s already has article id=%s; skipping (use --force).",
                    video["youtube_id"], existing["id"])
        return "exists"

    raw = tx["raw_text"] or ""
    cleaned = clean_transcript(raw)
    if len(cleaned.split()) < 20:
        logger.info("Video %s transcript too short (%d words); skipping.",
                    video["youtube_id"], len(cleaned.split()))
        return "too-short"

    article = extractor.extract(cleaned, video_title=video["title"], channel=video["channel"])
    markdown = article.to_markdown(
        source_channel=video["channel"],
        source_url=video["url"],
        video_title=video["title"],
    )
    slug = slugify(article.title)
    # Ensure slug uniqueness
    base_slug = slug
    counter = 1
    while get_article_by_slug(conn, slug):
        slug = f"{base_slug}-{counter}"
        counter += 1

    status = "published" if publish else "draft"
    if existing:
        update_article(
            conn, existing["id"],
            title=article.title, slug=slug, content_markdown=markdown,
            category=article.category, source_channel=video["channel"],
            source_url=video["url"], dtc_codes=",".join(article.dtc_codes),
            vehicle_refs=",".join(article.vehicle_refs),
            tools_used=",".join(article.tools_used), status=status,
        )
        article_id = existing["id"]
    else:
        article_id = create_article(
            conn, video_id=video_id, title=article.title, slug=slug,
            content_markdown=markdown, category=article.category,
            source_channel=video["channel"], source_url=video["url"],
            dtc_codes=",".join(article.dtc_codes),
            vehicle_refs=",".join(article.vehicle_refs),
            tools_used=",".join(article.tools_used), status=status,
        )
    set_article_tags(conn, article_id, article.tags)
    sync_article_to_fts(conn, article_id)
    update_video_status(conn, video_id, "published" if publish else "processed")

    # Also persist markdown file
    md_dir = settings.articles_dir_path
    md_dir.mkdir(parents=True, exist_ok=True)
    (md_dir / f"{slug}.md").write_text(markdown, encoding="utf-8")

    logger.info("Created article id=%s slug=%s (source=%s) for %s",
                article_id, slug, article.source, video["youtube_id"])
    return "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Process transcripts into articles.")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true", help="Process all videos with transcripts.")
    grp.add_argument("--video-id", help="Process a specific video (YouTube ID).")
    parser.add_argument("--db", default=None, help="Override database path.")
    parser.add_argument("--status", default="scraped",
                        help="Only process videos with this status (default: scraped).")
    parser.add_argument("--limit", type=int, default=0, help="Max videos to process (0 = all).")
    parser.add_argument("--force", action="store_true", help="Re-process existing articles.")
    parser.add_argument("--publish", action="store_true", help="Set articles to published status.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    db_path = args.db or settings.database_path
    init_db(db_path)

    extractor = LLMExtractor()

    if args.video_id:
        with get_conn(db_path) as conn:
            row = conn.execute("SELECT * FROM videos WHERE youtube_id = ?", (args.video_id,)).fetchone()
            if not row:
                print(f"ERROR: video {args.video_id} not found in DB.", file=sys.stderr)
                return 1
            status = process_one(conn, dict(row), extractor, force=args.force, publish=args.publish)
        print(f"Result for {args.video_id}: {status}")
        return 0 if status == "ok" else 1

    # --all path
    with get_conn(db_path) as conn:
        q = "SELECT * FROM videos WHERE status = ?"
        params: list = [args.status]
        if args.limit:
            q += " LIMIT ?"
            params.append(args.limit)
        videos = [dict(r) for r in conn.execute(q, params).fetchall()]

    print(f"Processing {len(videos)} videos with status '{args.status}'...")
    stats: dict[str, int] = {}
    for i, v in enumerate(videos, 1):
        with get_conn(db_path) as conn:
            status = process_one(conn, v, extractor, force=args.force, publish=args.publish)
        stats[status] = stats.get(status, 0) + 1
        print(f"  [{i}/{len(videos)}] {v['youtube_id']} -> {status}")

    print("\nSummary:", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())

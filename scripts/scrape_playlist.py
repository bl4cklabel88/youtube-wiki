#!/usr/bin/env python3
"""Scrape a YouTube playlist: list videos, upsert into DB, optionally fetch
transcripts for each.

Usage:
    python scripts/scrape_playlist.py --playlist "PLjzZLCfQx8TsHaJMsBYPvOqwhA-XuPa7l"
    python scripts/scrape_playlist.py --playlist "https://www.youtube.com/playlist?list=..."
    python scripts/scrape_playlist.py --playlist "... --scrape-transcripts
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import (  # noqa: E402
    add_source,
    get_conn,
    get_transcript_for_video,
    init_db,
    save_transcript,
    touch_source,
    update_video_status,
    upsert_video,
)
from app.scraper.youtube import YouTubeScraper  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape a YouTube playlist.")
    parser.add_argument("--playlist", required=True, help="Playlist ID or URL.")
    parser.add_argument("--db", default=None, help="Override database path.")
    parser.add_argument("--limit", type=int, default=0, help="Max videos (0 = all).")
    parser.add_argument("--scrape-transcripts", action="store_true",
                        help="Also fetch transcripts for each listed video.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    db_path = args.db or settings.database_path
    init_db(db_path)

    scraper = YouTubeScraper(
        proxy=settings.socks5_proxy or None,
        rate_limit_seconds=settings.rate_limit_seconds,
        max_retries=settings.max_retries,
    )

    print(f"Listing playlist: {args.playlist}")
    metas = scraper.list_playlist_videos(args.playlist)
    print(f"Found {len(metas)} videos")

    if args.limit:
        metas = metas[: args.limit]

    if args.dry_run:
        for m in metas:
            print(f"  {m.youtube_id}\t{m.title}")
        return 0

    source_id = None
    with get_conn(db_path) as conn:
        source_id = add_source(conn, args.playlist, "playlist", name=args.playlist, auto_scrape=True)

    processed = 0
    for i, m in enumerate(metas, 1):
        with get_conn(db_path) as conn:
            row_id = upsert_video(conn, m.youtube_id, m.title, m.channel, m.url,
                                  m.duration_seconds, status="pending")
            existing_tx = get_transcript_for_video(conn, row_id)

        if args.scrape_transcripts and not existing_tx:
            try:
                tx = scraper.fetch_transcript(m.youtube_id)
                if tx:
                    with get_conn(db_path) as conn:
                        save_transcript(conn, row_id, tx.raw_text,
                                        [s.to_dict() for s in tx.segments],
                                        tx.language, tx.is_auto_generated)
                        update_video_status(conn, row_id, "scraped")
                    print(f"  [{i}/{len(metas)}] {m.youtube_id} transcript OK")
                else:
                    with get_conn(db_path) as conn:
                        update_video_status(conn, row_id, "failed")
                    print(f"  [{i}/{len(metas)}] {m.youtube_id} no transcript")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Transcript fetch failed for %s: %s", m.youtube_id, exc)
                with get_conn(db_path) as conn:
                    update_video_status(conn, row_id, "failed")
        processed += 1

    if source_id:
        with get_conn(db_path) as conn:
            touch_source(conn, source_id)

    print(f"\nDone. Upserted {processed} videos (source id {source_id}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

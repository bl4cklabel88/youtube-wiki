#!/usr/bin/env python3
"""Scrape a YouTube channel: list videos, upsert into DB, optionally scrape
each video's transcript.

Usage:
    python scripts/scrape_channel.py --channel "@ScannerDanner" --filter-shorts
    python scripts/scrape_channel.py --channel "@AutomotiveFieldTheory" --filter-podcast --filter-shorts
    python scripts/scrape_channel.py --channel "@ScannerDanner" --filter-shorts --scrape-transcripts --limit 5
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
    get_video_by_youtube_id,
    init_db,
    save_transcript,
    touch_source,
    update_video_status,
    upsert_video,
)
from app.scraper.youtube import YouTubeScraper  # noqa: E402

logger = logging.getLogger(__name__)

PODCAST_KEYWORDS = ("podcast", "live stream", "livestream", "live q&a", "qa session",
                    "office hours", "panel discussion", "roundtable")


def _is_podcast(title: str) -> bool:
    lowered = title.lower()
    return any(k in lowered for k in PODCAST_KEYWORDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape a YouTube channel.")
    parser.add_argument("--channel", required=True, help="Channel URL or @handle.")
    parser.add_argument("--db", default=None, help="Override database path.")
    parser.add_argument("--filter-shorts", action="store_true", help="Skip Shorts.")
    parser.add_argument("--filter-podcast", action="store_true", help="Skip podcast/live episodes.")
    parser.add_argument("--limit", type=int, default=0, help="Max videos to process (0 = all).")
    parser.add_argument("--scrape-transcripts", action="store_true",
                        help="Also fetch transcripts for each listed video.")
    parser.add_argument("--dry-run", action="store_true", help="Only list videos, don't write DB.")
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

    channel_input = args.channel
    if not channel_input.startswith("http"):
        channel_input = f"https://www.youtube.com/{channel_input.lstrip('/')}"

    print(f"Listing videos for channel: {channel_input}")
    metas = scraper.list_channel_videos(channel_input)
    print(f"Found {len(metas)} videos total")

    kept = []
    skipped_shorts = 0
    skipped_podcast = 0
    for m in metas:
        if args.filter_shorts and m.is_shorts:
            skipped_shorts += 1
            continue
        if args.filter_podcast and _is_podcast(m.title):
            skipped_podcast += 1
            continue
        kept.append(m)
        if args.limit and len(kept) >= args.limit:
            break

    print(f"After filters: {len(kept)} videos "
          f"(skipped {skipped_shorts} shorts, {skipped_podcast} podcast/live)")

    if args.dry_run:
        for m in kept[:50]:
            print(f"  {m.youtube_id}\t{m.title}")
        return 0

    source_id = None
    with get_conn(db_path) as conn:
        source_id = add_source(conn, channel_input, "channel", name=channel_input, auto_scrape=True)

    processed = 0
    for i, m in enumerate(kept, 1):
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
                    print(f"  [{i}/{len(kept)}] {m.youtube_id} transcript OK ({len(tx.raw_text.split())} words)")
                else:
                    with get_conn(db_path) as conn:
                        update_video_status(conn, row_id, "failed")
                    print(f"  [{i}/{len(kept)}] {m.youtube_id} no transcript")
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

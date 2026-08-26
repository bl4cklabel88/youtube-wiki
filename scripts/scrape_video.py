#!/usr/bin/env python3
"""Scrape a single YouTube video: metadata + transcript into the database.

Usage:
    python scripts/scrape_video.py --url "https://www.youtube.com/watch?v=98lyvpPonxQ"
    python scripts/scrape_video.py --url "https://youtu.be/98lyvpPonxQ"
    python scripts/scrape_video.py --url 98lyvpPonxQ
    python scripts/scrape_video.py --url ... --save-transcript
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import (  # noqa: E402
    get_conn,
    get_transcript_for_video,
    get_video_by_youtube_id,
    init_db,
    save_transcript,
    update_video_status,
    upsert_video,
)
from app.scraper.youtube import (  # noqa: E402
    YouTubeScraper,
    extract_video_id,
    save_transcript_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape a single YouTube video.")
    parser.add_argument("--url", required=True, help="YouTube video URL or ID.")
    parser.add_argument("--db", default=None, help="Override database path.")
    parser.add_argument("--save-transcript", action="store_true",
                        help="Also write transcript JSON/TXT to the transcripts dir.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    db_path = args.db or settings.database_path
    init_db(db_path)

    video_id = extract_video_id(args.url)
    if not video_id:
        print(f"ERROR: cannot extract video ID from {args.url!r}", file=sys.stderr)
        return 1

    scraper = YouTubeScraper(
        proxy=settings.socks5_proxy or None,
        rate_limit_seconds=settings.rate_limit_seconds,
        max_retries=settings.max_retries,
    )

    print(f"Scraping video: {video_id}")
    result = scraper.scrape_video(video_id)
    meta = result["meta"]
    transcript = result["transcript"]

    with get_conn(db_path) as conn:
        row_id = upsert_video(
            conn,
            youtube_id=meta.youtube_id,
            title=meta.title,
            channel=meta.channel,
            url=meta.url,
            duration_seconds=meta.duration_seconds,
            status="scraped" if transcript else "failed",
        )
        if transcript:
            save_transcript(
                conn,
                video_id=row_id,
                raw_text=transcript.raw_text,
                segments=[s.to_dict() for s in transcript.segments],
                language=transcript.language,
                is_auto_generated=transcript.is_auto_generated,
            )
            if args.save_transcript:
                save_transcript_json(transcript, settings.transcripts_dir_path)
        else:
            update_video_status(conn, row_id, "failed")

    print(f"Title: {meta.title}")
    print(f"Channel: {meta.channel}")
    print(f"Duration: {meta.duration_seconds}s")
    if transcript:
        print(f"Transcript: {len(transcript.segments)} segments, "
              f"{len(transcript.raw_text.split())} words")
    else:
        print("Transcript: NOT AVAILABLE (video marked failed)")
    print(f"DB row id: {row_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

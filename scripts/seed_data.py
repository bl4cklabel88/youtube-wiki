#!/usr/bin/env python3
"""Seed the videos table from the pre-seeded data/*.txt video lists.

Each data file is a TSV with columns: youtube_id<TAB>title

Files are mapped to a source channel name so the wiki can filter by channel.

Usage:
    python scripts/seed_data.py
    python scripts/seed_data.py --reset   # wipe videos first
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BASE_DIR, settings  # noqa: E402
from app.database import get_conn, init_db, upsert_video  # noqa: E402

# Map each seed file to its channel display name.
SEED_FILES: dict[str, str] = {
    "scannerdanner_all.txt": "ScannerDanner",
    "aft_filtered.txt": "Automotive Field Theory",
    "playlist_motorage.txt": "Motor Age Training",
}


def parse_seed_file(path: Path) -> list[tuple[str, str]]:
    """Parse a TSV file of youtube_id<TAB>title lines.

    Handles both real tab characters and literal ``\\t`` escape sequences
    (some exports write the backslash-t literally).
    """
    entries: list[tuple[str, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Normalize literal \t escapes to real tabs
        if "\\t" in line and "\t" not in line:
            line = line.replace("\\t", "\t")
        parts = line.split("\t")
        if len(parts) < 2:
            print(f"  ! skipping malformed line {lineno}: {line[:80]!r}")
            continue
        youtube_id, title = parts[0].strip(), parts[1].strip()
        if not youtube_id or not title:
            continue
        entries.append((youtube_id, title))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed videos table from data/*.txt")
    parser.add_argument("--db", default=None, help="Override database path.")
    parser.add_argument("--reset", action="store_true", help="Delete existing videos before seeding.")
    args = parser.parse_args()

    db_path = args.db or settings.database_path
    init_db(db_path)

    total = 0
    with get_conn(db_path) as conn:
        if args.reset:
            deleted = conn.execute("DELETE FROM videos").rowcount
            print(f"Reset: removed {deleted} existing videos.")

        for filename, channel in SEED_FILES.items():
            path = BASE_DIR / "data" / filename
            if not path.exists():
                print(f"  ! missing seed file: {path}")
                continue
            entries = parse_seed_file(path)
            added = 0
            for youtube_id, title in entries:
                url = f"https://www.youtube.com/watch?v={youtube_id}"
                upsert_video(conn, youtube_id, title, channel, url)
                added += 1
            total += added
            print(f"  {filename}: {added} videos ({channel})")

    print(f"\nDone. Total videos seeded/verified: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

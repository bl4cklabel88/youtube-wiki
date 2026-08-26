#!/usr/bin/env python3
"""Initialize the SQLite database (schema + FTS5 tables).

Usage:
    python scripts/init_db.py
    python scripts/init_db.py --db /path/to/wiki.db
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import init_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the wiki database.")
    parser.add_argument("--db", default=None, help="Override database path.")
    args = parser.parse_args()

    db_path = args.db or settings.database_path
    print(f"Initializing database at: {db_path}")
    init_db(db_path)
    print("Database initialized successfully (schema + FTS5).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

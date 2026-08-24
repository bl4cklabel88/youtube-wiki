"""Channel/playlist subscription management helpers."""
from __future__ import annotations

import logging
from typing import Optional

from ..database import (
    add_source,
    get_conn,
    list_sources,
    remove_source,
    touch_source,
)

logger = logging.getLogger(__name__)


def subscribe(conn, url: str, type_: str, name: Optional[str] = None,
              auto_scrape: bool = False) -> int:
    """Add a channel/playlist/video source to track."""
    return add_source(conn, url, type_, name, auto_scrape)


def unsubscribe(source_id: int) -> None:
    with get_conn() as conn:
        remove_source(conn, source_id)


def all_sources() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in list_sources(conn)]


def mark_scraped(source_id: int) -> None:
    with get_conn() as conn:
        touch_source(conn, source_id)

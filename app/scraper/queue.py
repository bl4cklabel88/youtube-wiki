"""Job queue backed by SQLite.

Status flow: pending -> running -> done | failed

Used for both scraping and transcript-processing jobs so the admin panel can
show queue status and the worker can claim jobs safely.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from ..database import (
    claim_next_job,
    enqueue_job,
    fail_job,
    finish_job,
    get_conn,
    list_jobs,
    reset_stuck_jobs,
)

logger = logging.getLogger(__name__)


class JobQueue:
    """High-level wrapper around the SQLite jobs table."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def enqueue(self, video_id: int, job_type: str = "scrape", payload: Optional[str] = None) -> int:
        with get_conn(self.db_path) as conn:
            return enqueue_job(conn, video_id, job_type, payload)

    def claim(self, job_type: Optional[str] = None) -> Optional[dict]:
        """Atomically claim the next pending job (returns dict or None)."""
        with get_conn(self.db_path) as conn:
            row = claim_next_job(conn, job_type)
            return dict(row) if row else None

    def finish(self, job_id: int, status: str, error: Optional[str] = None) -> None:
        with get_conn(self.db_path) as conn:
            finish_job(conn, job_id, status, error)

    def fail(self, job_id: int, error: str) -> None:
        with get_conn(self.db_path) as conn:
            fail_job(conn, job_id, error)

    def list(self, status: Optional[str] = None, limit: int = 100) -> list[dict]:
        with get_conn(self.db_path) as conn:
            return [dict(r) for r in list_jobs(conn, status=status, limit=limit)]

    def reset_stuck(self) -> int:
        with get_conn(self.db_path) as conn:
            return reset_stuck_jobs(conn)

    def counts(self) -> dict[str, int]:
        """Return job counts grouped by status."""
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

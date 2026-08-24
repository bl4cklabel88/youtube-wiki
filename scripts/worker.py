#!/usr/bin/env python3
"""Background worker: consume queued jobs (scrape + process).

Run continuously (e.g. via systemd) or in a loop:
    python scripts/worker.py --once
    python scripts/worker.py --loop --sleep 5

Jobs are claimed atomically from the SQLite-backed queue so multiple workers
can run concurrently without double-processing.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import (  # noqa: E402
    get_conn,
    get_transcript_for_video,
    get_video,
    init_db,
    save_transcript,
    update_video_status,
)
from app.processor.cleaner import clean_transcript  # noqa: E402
from app.processor.extractor import LLMExtractor  # noqa: E402
from app.scraper.queue import JobQueue  # noqa: E402
from app.scraper.youtube import YouTubeScraper  # noqa: E402
from scripts.process_transcripts import process_one  # noqa: E402

logger = logging.getLogger(__name__)


def run_job(job: dict, scraper: YouTubeScraper, extractor: LLMExtractor) -> str:
    """Execute one job. Returns 'done' or raises."""
    job_type = job.get("job_type", "scrape")
    video_id = job.get("video_id")

    if job_type == "scrape":
        with get_conn() as conn:
            video = get_video(conn, video_id)
            if not video:
                raise RuntimeError(f"Video id {video_id} not found")
            youtube_id = video["youtube_id"]
        result = scraper.scrape_video(youtube_id)
        meta = result["meta"]
        transcript = result["transcript"]
        with get_conn() as conn:
            from app.database import upsert_video
            row_id = upsert_video(conn, meta.youtube_id, meta.title, meta.channel,
                                  meta.url, meta.duration_seconds,
                                  status="scraped" if transcript else "failed")
            if transcript:
                save_transcript(conn, row_id, transcript.raw_text,
                                [s.to_dict() for s in transcript.segments],
                                transcript.language, transcript.is_auto_generated)
            else:
                update_video_status(conn, row_id, "failed")
        if not transcript:
            raise RuntimeError(f"No transcript available for {youtube_id}")
        # Chain: enqueue a process job
        with get_conn() as conn:
            from app.database import enqueue_job
            enqueue_job(conn, row_id, "process")
        return "done"

    if job_type == "process":
        with get_conn() as conn:
            video = get_video(conn, video_id)
            if not video:
                raise RuntimeError(f"Video id {video_id} not found")
            status = process_one(conn, dict(video), extractor, force=False, publish=True)
        if status != "ok":
            raise RuntimeError(f"Processing failed: {status}")
        return "done"

    raise RuntimeError(f"Unknown job type: {job_type}")


def main() -> int:
    parser = argparse.ArgumentParser(description="YouTube Wiki job worker.")
    parser.add_argument("--once", action="store_true", help="Run a single job and exit.")
    parser.add_argument("--loop", action="store_true", help="Loop forever.")
    parser.add_argument("--sleep", type=float, default=5.0, help="Sleep between polls (loop).")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    init_db()
    queue = JobQueue()
    scraper = YouTubeScraper(
        proxy=settings.socks5_proxy or None,
        rate_limit_seconds=settings.rate_limit_seconds,
        max_retries=settings.max_retries,
    )
    extractor = LLMExtractor()

    def _tick() -> bool:
        job = queue.claim()
        if not job:
            return False
        logger.info("Running job #%s (%s) video_id=%s", job["id"], job["job_type"], job["video_id"])
        try:
            run_job(job, scraper, extractor)
            queue.finish(job["id"], "done")
            logger.info("Job #%s done", job["id"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job #%s failed", job["id"])
            queue.fail(job["id"], str(exc)[:500])
        return True

    if args.once:
        ran = _tick()
        print("Ran a job." if ran else "No pending jobs.")
        return 0

    if args.loop:
        logger.info("Worker loop started (sleep=%ss). Ctrl-C to stop.", args.sleep)
        while True:
            try:
                busy = _tick()
                if not busy:
                    time.sleep(args.sleep)
            except KeyboardInterrupt:
                logger.info("Worker stopped.")
                return 0
            except Exception:  # noqa: BLE001
                logger.exception("Worker loop error; continuing")
                time.sleep(args.sleep)

    # Default: drain all pending jobs then exit
    drained = 0
    while _tick():
        drained += 1
    print(f"Drained {drained} jobs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

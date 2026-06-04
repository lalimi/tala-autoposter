"""Orchestrator + scheduler for the Tala autonomous Threads autoposter.

Pipeline (every POST_INTERVAL_HOURS): MemoryAgent -> ParserAgent -> WriterAgent -> MemoryAgent -> PublisherAgent
"""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from config import settings
from pipeline import run_pipeline


def _setup_logging() -> logging.Logger:
    handler = TimedRotatingFileHandler(
        settings.LOGS_DIR / "autoposter.log",
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    handler.suffix = "%Y-%m-%d"
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[handler, logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("tala")


logger = _setup_logging()


def _safe_run() -> None:
    """Scheduler entrypoint — swallow everything so the loop keeps running."""
    try:
        run_pipeline(publish=True)
    except Exception as exc:
        logger.exception("pipeline error: %s", exc)


def print_stats() -> None:
    from agents.memory_agent import MemoryAgent

    rows = MemoryAgent().recent_posts(10)
    if not rows:
        print("no posts yet")
        return
    print(f"{'published_at':<28} {'topic':<18} {'status':<10} text")
    for r in rows:
        ts = r["published_at"] or "-"
        text = (r.get("text") or "").replace("\n", " ")[:50]
        print(f"{ts:<28} {r['topic']:<18} {r['status']:<10} {text}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tala autonomous Threads autoposter")
    parser.add_argument("--test", action="store_true",
                        help="run pipeline once, print post, do NOT publish")
    parser.add_argument("--dry-run", action="store_true",
                        help="run pipeline, print post, skip publishing")
    parser.add_argument("--publish", action="store_true",
                        help="run pipeline once and PUBLISH for real to Threads")
    parser.add_argument("--stats", action="store_true",
                        help="print the last 10 posts from memory.db")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    if args.test or args.dry_run:
        text = run_pipeline(publish=False)
        print("\n----- GENERATED POST -----\n")
        print(text)
        print("\n--------------------------\n")
        return

    if args.publish:
        text = run_pipeline(publish=True)
        print("\n----- PUBLISHED POST -----\n")
        print(text)
        print("\n--------------------------\n")
        return

    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    # No next_run_time: the first post is one interval out, so a restart/reboot
    # never fires an immediate post. Use `--publish` to post on demand.
    scheduler.add_job(
        _safe_run,
        "interval",
        hours=settings.POST_INTERVAL_HOURS,
    )
    logger.info(
        "scheduler started | every %sh | first auto-post in %sh "
        "(run `python main.py --publish` to post now)",
        settings.POST_INTERVAL_HOURS, settings.POST_INTERVAL_HOURS,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler stopped")


if __name__ == "__main__":
    main()

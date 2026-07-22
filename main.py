"""Orchestrator + scheduler for the Tala autonomous Threads autoposter.

Pipeline (every POST_INTERVAL_HOURS): MemoryAgent -> ParserAgent -> WriterAgent -> MemoryAgent -> PublisherAgent
"""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from config import settings
from config.brands import get_brand
from pipeline import run_comment, run_metrics, run_pipeline


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


def _safe_run(brand) -> None:
    """Scheduler entrypoint — swallow everything so the loop keeps running."""
    try:
        run_pipeline(brand, publish=True)
    except Exception as exc:
        logger.exception("pipeline error: %s", exc)


def print_stats(brand) -> None:
    from agents.memory_agent import MemoryAgent

    rows = MemoryAgent(brand).recent_posts(10)
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
    parser.add_argument("--brand", default="tala",
                        help="which account to run: tala (default), blacksea or denys")
    parser.add_argument("--test", action="store_true",
                        help="run pipeline once, print post, do NOT publish")
    parser.add_argument("--dry-run", action="store_true",
                        help="run pipeline, print post, skip publishing")
    parser.add_argument("--publish", action="store_true",
                        help="run pipeline once and PUBLISH for real to Threads")
    parser.add_argument("--comment", action="store_true",
                        help="reply once under a scraped candidate post and PUBLISH")
    parser.add_argument("--metrics", action="store_true",
                        help="fetch + store Threads insights for posts >=24h old")
    parser.add_argument("--tick", action="store_true",
                        help="one SELF-THROTTLED tick for systemd/cron timers: "
                             "publish only if the brand's min-gap has elapsed "
                             "(combine with --comment for a comment tick)")
    parser.add_argument("--stats", action="store_true",
                        help="print the last 10 posts from this brand's history")
    args = parser.parse_args()

    brand = get_brand(args.brand)

    if args.stats:
        print_stats(brand)
        return

    if args.metrics:
        n = run_metrics(brand)
        print(f"metrics updated for {n} post(s)")
        return

    if args.tick:
        fn = run_comment if args.comment else run_pipeline
        text = fn(brand, publish=True, respect_min_gap=True)
        print(text or "(skipped: min-gap not elapsed / no candidate)")
        return

    if args.comment:
        text = run_comment(brand, publish=not (args.test or args.dry_run))
        print("\n----- COMMENT -----\n")
        print(text or "(skipped: throttled / disabled / no candidate)")
        print("\n-------------------\n")
        return

    if args.test or args.dry_run:
        text = run_pipeline(brand, publish=False)
        print("\n----- GENERATED POST -----\n")
        print(text)
        print("\n--------------------------\n")
        return

    if args.publish:
        text = run_pipeline(brand, publish=True)
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
        args=[brand],
    )
    logger.info(
        "scheduler started | brand=%s | every %sh | first auto-post in %sh "
        "(run `python main.py --publish` to post now)",
        brand.key, settings.POST_INTERVAL_HOURS, settings.POST_INTERVAL_HOURS,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler stopped")


if __name__ == "__main__":
    main()

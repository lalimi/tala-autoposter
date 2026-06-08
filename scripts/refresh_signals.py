"""Decoupled signal refresher — RUN ON A MACHINE WITH A BROWSER (Mac/VPS).

Vercel has no browser, so scraping lives here. This scrapes Threads via
Playwright (parser/scraper.fetch_all) for every topic keyword + a sample of the
tracked top-reach accounts, and writes the results into Supabase `tala_signals`.
The Vercel cron then reads those cached signals when writing posts.

Schedule it (launchd / cron) every few hours. Requires:
  * SUPABASE_SERVICE_KEY in env/.env
  * a valid scraper session (parser/scout_session.json) — see parser/scraper.py

Run manually:  python -m scripts.refresh_signals
"""
from __future__ import annotations

import json
import logging
import random

import store
from config import settings
from parser.scraper import fetch_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("tala.refresh")

PEER_SAMPLE = 10          # accounts scraped per refresh (rotates over runs)
MAX_TOTAL = 300           # keep broad keyword coverage, not just the top 20


def _signal_rows(posts: list[dict], kind: str) -> list[dict]:
    return [
        {
            "kind": kind,
            "keyword": p.get("keyword"),
            "source": p.get("source"),
            "text": p.get("text", "").strip(),
            "url": p.get("url"),
            "likes": p.get("likes", 0),
        }
        for p in posts
        if p.get("text")
    ]


def main() -> None:
    topics = json.load(open(settings.TOPICS_FILE, encoding="utf-8"))["topics"]
    keywords = list(dict.fromkeys(kw for t in topics for kw in t["keywords"]))

    accounts_file = settings.CONFIG_DIR / "accounts.json"
    accounts = json.load(open(accounts_file, encoding="utf-8")).get("accounts", [])
    if len(accounts) > PEER_SAMPLE:
        accounts = random.sample(accounts, PEER_SAMPLE)

    log.info("scraping %d keywords + %d accounts...", len(keywords), len(accounts))
    data = fetch_all(keywords, accounts, max_total=MAX_TOTAL)

    kw_rows = _signal_rows(data.get("keywords", []), "keyword")
    peer_rows = _signal_rows(data.get("profiles", []), "peer")

    if not kw_rows and not peer_rows:
        log.warning("scraper returned nothing — keeping existing signals (no wipe)")
        return

    # Only replace a kind if we actually got fresh data for it.
    if kw_rows:
        store.replace_signals("keyword", kw_rows)
    if peer_rows:
        store.replace_signals("peer", peer_rows)
    log.info("stored %d keyword + %d peer signals", len(kw_rows), len(peer_rows))

    # Queue keyword posts as comment candidates (those that carry a Threads id).
    targets = [
        {"thread_id": p["id"], "username": p.get("source"), "text": p.get("text", ""),
         "url": p.get("url"), "likes": p.get("likes", 0), "keyword": p.get("keyword")}
        for p in data.get("keywords", []) if p.get("id") and p.get("text")
    ]
    if targets:
        store.save_comment_targets(targets)
        log.info("queued %d comment targets", len(targets))


if __name__ == "__main__":
    main()

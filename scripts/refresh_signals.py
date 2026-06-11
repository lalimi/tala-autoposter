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
KEYWORD_SAMPLE = 18       # keywords scraped per run (random; rotates over the day)
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


def _load_keywords(path) -> list[str]:
    try:
        return json.load(open(path, encoding="utf-8")).get("keywords", [])
    except (OSError, ValueError):
        return []


def main() -> None:
    topics = json.load(open(settings.TOPICS_FILE, encoding="utf-8"))["topics"]
    topic_kws = list(dict.fromkeys(kw for t in topics for kw in t["keywords"]))
    # Broader, general/humour keywords used ONLY to find posts to comment under.
    comment_kws = _load_keywords(settings.CONFIG_DIR / "comment_keywords.json")
    keywords = list(dict.fromkeys(topic_kws + comment_kws))
    # Scrape a rotating random subset per run so one tick stays well under the
    # systemd timeout; over the day's runs this covers everything.
    if len(keywords) > KEYWORD_SAMPLE:
        keywords = random.sample(keywords, KEYWORD_SAMPLE)

    accounts_file = settings.CONFIG_DIR / "accounts.json"
    accounts = json.load(open(accounts_file, encoding="utf-8")).get("accounts", [])
    if len(accounts) > PEER_SAMPLE:
        accounts = random.sample(accounts, PEER_SAMPLE)

    log.info("scraping %d keywords + %d accounts...", len(keywords), len(accounts))
    data = fetch_all(keywords, accounts, max_total=MAX_TOTAL)

    # Signals that feed the WRITER come only from the niche topic keywords;
    # the general comment keywords are for the comment queue, not for posts.
    topic_set = set(topic_kws)
    kw_for_signals = [p for p in data.get("keywords", []) if p.get("keyword") in topic_set]
    kw_rows = _signal_rows(kw_for_signals, "keyword")
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

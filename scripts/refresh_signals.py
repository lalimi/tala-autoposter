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
from config.brands import DENYS, TALA
from parser.scraper import fetch_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("tala.refresh")

# Brands that get scraped seed material. Each contributes its own topic keywords
# (→ its own {prefix}_signals). Accounts are shared (peer signals are brand-
# agnostic hook/structure orientation), so one account scrape feeds all of them.
SCRAPE_BRANDS = (TALA, DENYS)

PEER_SAMPLE = 10          # accounts scraped per refresh (rotates over runs)
KEYWORD_SAMPLE = 18       # total keyword searches per run (split across brands)
MAX_TOTAL = 300           # keep broad keyword coverage, not just the top 20


def _topic_keywords(topics_file) -> list[str]:
    try:
        topics = json.load(open(topics_file, encoding="utf-8"))["topics"]
    except (OSError, ValueError, KeyError):
        return []
    return list(dict.fromkeys(kw for t in topics for kw in t["keywords"]))


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
    # Per-brand topic keywords (each brand seeds from its own → {prefix}_signals).
    brand_kws = {b: _topic_keywords(b.topics_file) for b in SCRAPE_BRANDS}
    # General/humour keywords used ONLY to find posts to comment under (Tala).
    comment_kws = _load_keywords(settings.CONFIG_DIR / "comment_keywords.json")

    # Split the per-run keyword budget across brands so one tick stays under the
    # systemd timeout; random rotation covers everything over the day. Leave a
    # slice for comment keywords.
    n = len(brand_kws) + (1 if comment_kws else 0)
    per = max(3, KEYWORD_SAMPLE // n)

    def _sample(kws):
        return random.sample(kws, per) if len(kws) > per else list(kws)

    brand_sample = {b: _sample(kws) for b, kws in brand_kws.items()}
    comment_sample = _sample(comment_kws) if comment_kws else []
    # One browser session scrapes the union of everything.
    all_keywords = list(dict.fromkeys(
        [kw for s in brand_sample.values() for kw in s] + comment_sample
    ))

    accounts_file = settings.CONFIG_DIR / "accounts.json"
    accounts = json.load(open(accounts_file, encoding="utf-8")).get("accounts", [])
    if len(accounts) > PEER_SAMPLE:
        accounts = random.sample(accounts, PEER_SAMPLE)

    log.info("scraping %d keywords (%s) + %d accounts...", len(all_keywords),
             ", ".join(f"{b.key}:{len(s)}" for b, s in brand_sample.items()), len(accounts))
    data = fetch_all(all_keywords, accounts, max_total=MAX_TOTAL)

    kw_posts = data.get("keywords", [])
    # Peer posts (tracked accounts) are brand-agnostic hook/structure orientation.
    peer_rows = _signal_rows(data.get("profiles", []), "peer")

    if not kw_posts and not peer_rows:
        log.warning("scraper returned nothing — keeping existing signals (no wipe)")
        return

    # Write per brand: its own keyword posts, plus the shared peer batch.
    for brand, kws in brand_kws.items():
        kset = set(kws)
        kw_rows = _signal_rows([p for p in kw_posts if p.get("keyword") in kset], "keyword")
        if kw_rows:
            store.replace_signals("keyword", kw_rows, prefix=brand.table_prefix)
        if peer_rows:
            store.replace_signals("peer", peer_rows, prefix=brand.table_prefix)
        log.info("[%s] stored %d keyword + %d peer signals",
                 brand.key, len(kw_rows), len(peer_rows))

    # Comment candidates → Tala's queue only (only Tala comments for now).
    # Never queue our own accounts' posts — replying to ourselves from one IP is
    # a coordinated-behaviour flag.
    targets = [
        {"thread_id": p["id"], "username": p.get("source"), "text": p.get("text", ""),
         "url": p.get("url"), "likes": p.get("likes", 0), "keyword": p.get("keyword")}
        for p in kw_posts
        if p.get("id") and p.get("text")
        and (p.get("source") or "").lstrip("@").lower() not in settings.OWN_HANDLES
    ]
    if targets:
        store.save_comment_targets(targets)
        log.info("queued %d comment targets", len(targets))


if __name__ == "__main__":
    main()

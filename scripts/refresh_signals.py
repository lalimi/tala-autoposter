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
from agents import keyword_search
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
API_SEARCH_KEYWORDS = 6   # keywords queried through the official API per run
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

    # Donor accounts are per brand now. The shared list was global and generic
    # (motivational, SQL careers, Indonesian productivity), so peer signals — the
    # bulk of the material — never matched any brand's niche.
    brand_accounts = {}
    for b in SCRAPE_BRANDS:
        names = []
        if b.accounts_file:
            try:
                names = json.load(open(b.accounts_file, encoding="utf-8")).get("accounts", [])
            except (OSError, ValueError):
                names = []
        per_brand = max(3, PEER_SAMPLE // max(1, len(SCRAPE_BRANDS)))
        brand_accounts[b] = (random.sample(names, per_brand)
                             if len(names) > per_brand else list(names))
    accounts = list(dict.fromkeys(a for v in brand_accounts.values() for a in v))

    log.info("scraping %d keywords (%s) + %d donor accounts (%s)...",
             len(all_keywords),
             ", ".join(f"{b.key}:{len(s)}" for b, s in brand_sample.items()),
             len(accounts),
             ", ".join(f"{b.key}:{len(v)}" for b, v in brand_accounts.items()))
    data = fetch_all(all_keywords, accounts, max_total=MAX_TOTAL)

    kw_posts = data.get("keywords", [])
    # Accumulate per-author reach so an outlier can later be told apart from a
    # big account's ordinary day.
    try:
        store.bump_author_stats(kw_posts + data.get("profiles", []))
    except Exception as exc:  # never fail a scrape over bookkeeping
        log.warning("author stats not updated: %s", exc)
    # Peer posts (tracked accounts) are brand-agnostic hook/structure orientation.
    profiles = data.get("profiles", [])

    if not kw_posts and not profiles:
        log.warning("scraper returned nothing — keeping existing signals (no wipe)")
        return

    relevant_by_brand: dict[str, list] = {}
    # Write per brand: its own keyword posts, plus the shared peer batch.
    for brand, kws in brand_kws.items():
        kset = set(kws)
        mine = [p for p in kw_posts if p.get("keyword") in kset]
        raw_mine = list(mine)
        # Keyword search is loose — it has handed the writer posts about mortgage
        # rates and politics. Score the strongest candidates against the brand's
        # niche and drop the ones that only matched a word.
        if brand.niche and mine:
            from agents.relevance import filter_relevant

            before = len(mine)
            mine = filter_relevant(brand.niche, mine)
            log.info("[%s] relevance: %d -> %d candidates", brand.key, before, len(mine))
        # Comment targets come from the SAME vetted list: they used to be built
        # from raw scrape output, so 87% of them were off-niche and the writer
        # SKIPped them — each skip burns a target permanently and the queue
        # drained without ever landing a comment.
        relevant_by_brand[brand.key] = mine
        kw_rows = _signal_rows(mine, "keyword")
        # Only this brand's own donors, not everyone's.
        mine_names = {f"@{a}" for a in brand_accounts.get(brand, [])}
        peer_rows = _signal_rows(
            [p for p in profiles if p.get("keyword") in mine_names], "peer")
        if kw_rows:
            store.replace_signals("keyword", kw_rows, prefix=brand.table_prefix)
        if peer_rows:
            store.replace_signals("peer", peer_rows, prefix=brand.table_prefix)
        log.info("[%s] stored %d keyword + %d peer signals",
                 brand.key, len(kw_rows), len(peer_rows))

    # Comment candidates, per commenting brand — each gets the posts found by ITS
    # own keywords, so Denys replies in his niche and Tala in hers. Never queue
    # our own accounts' posts: replying to ourselves from one IP is a
    # coordinated-behaviour flag.
    for brand, kws in brand_kws.items():
        if not brand.comments_enabled:
            continue
        kset = set(kws)

        # Prefer the OFFICIAL keyword search: its ids are real Graph media ids,
        # so those replies go through the API instead of the browser. It returns
        # nothing useful until the app is approved for threads_keyword_search,
        # so the scrape below still runs as the fallback.
        api_targets: list[dict] = []
        for kw in random.sample(kws, min(len(kws), API_SEARCH_KEYWORDS)):
            posts = keyword_search.search(kw, brand, search_type="TOP")
            api_targets += keyword_search.as_comment_targets(
                posts, kw, own_handles=settings.OWN_HANDLES)
        if api_targets:
            store.save_comment_targets(api_targets, prefix=brand.table_prefix)
            log.info("[%s] queued %d comment targets from the API",
                     brand.key, len(api_targets))

        targets = [
            {"thread_id": p["id"], "username": p.get("source"), "text": p.get("text", ""),
             "url": p.get("url"), "likes": p.get("likes", 0), "keyword": p.get("keyword"),
             "source": "scrape"}
            for p in relevant_by_brand.get(brand.key, [])
            if p.get("id") and p.get("text")
            and (p.get("source") or "").lstrip("@").lower() not in settings.OWN_HANDLES
        ]
        if targets:
            store.save_comment_targets(targets, prefix=brand.table_prefix)
            log.info("[%s] queued %d comment targets from the scraper",
                     brand.key, len(targets))


if __name__ == "__main__":
    main()

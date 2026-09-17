"""Official Threads keyword search — GET /keyword_search.

Meta added this endpoint after the scraper was written, and it beats scraping on
every axis that matters here:

  * no browser, no cookie jar, no Playwright — so nothing to ban for scraping
  * `search_type=TOP` returns the high-reach posts for a keyword, which is
    exactly what we want both as writer peer-signal and as a comment target
  * the returned `id` is a real GRAPH MEDIA ID, so a reply can be published
    through the API (`reply_to_id`). Scraped ids are web pks from a different
    id space, which is why API replies to scraped posts 500'd and commenting
    had to fall back to driving the web UI.

PERMISSION: needs `threads_keyword_search` on top of `threads_basic`. Until the
app is approved for it, the endpoint only returns posts owned by the
authenticated user — it does not error, it just comes back near-empty. Use
`--check` to see which of the two states this token is in.

    python -m agents.keyword_search --brand tala --q "ранкова рутина"
    python -m agents.keyword_search --brand tala --check
"""
from __future__ import annotations

import logging

import requests

from agents.token_manager import get_valid_token
from config import settings
from config.brands import TALA, Brand

BASE_URL = "https://graph.threads.net/v1.0"
FIELDS = ("id,text,username,permalink,timestamp,media_type,"
          "has_replies,is_quote_post,is_reply")

logger = logging.getLogger("tala.search")


def search(keyword: str, brand: Brand = TALA, search_type: str = "TOP",
           limit: int = 25, media_type: str | None = None,
           search_mode: str | None = None, force: bool = False) -> list[dict]:
    """Public Threads posts for `keyword`, top-or-recent first.

    search_type: "TOP" (high engagement) or "RECENT".
    search_mode:  "TAG" searches the topic tag rather than free text — that is
                  how you follow a trending topic once you know its name.
    Returns [] on any API failure so a bad keyword never takes the caller down.
    """
    if not settings.THREADS_API_SEARCH and not force:
        return []
    params = {
        "q": keyword,
        "search_type": search_type,
        "fields": FIELDS,
        "limit": limit,
        "access_token": get_valid_token(brand),
    }
    if media_type:
        params["media_type"] = media_type
    if search_mode:
        params["search_mode"] = search_mode
    try:
        r = requests.get(f"{BASE_URL}/keyword_search", params=params, timeout=20)
        if not r.ok:
            # Body carries Meta's reason (missing permission, bad token, ...).
            logger.warning("keyword_search %s -> %s: %s",
                           keyword, r.status_code, r.text[:200])
            return []
        return r.json().get("data", []) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_search %s failed: %s", keyword, exc)
        return []


def trending_topics(brand: Brand = TALA, country_code: str = "UA",
                    force: bool = False) -> list[dict]:
    """What Threads is trending on right now, per country.

    GET /trending_topics?country_code=XX. The path is real — probing it without
    the parameter returns "The parameter country_code is required" rather than
    404. That error is only parameter validation though, which runs BEFORE the
    permission check, so it says nothing about access: with the country_code
    supplied, UA/US/GB/PL/DE/CA/AU all came back 200 with an empty list because
    threads_trending_topics is not granted yet (business verification pending).
    Meta answers empty rather than erroring, exactly as keyword_search does.

    Returns [] on failure, so a bad country or an API hiccup never takes a run
    down. Shape is whatever Meta sends; callers should use .get().
    """
    if not settings.THREADS_API_SEARCH and not force:
        return []
    try:
        r = requests.get(
            f"{BASE_URL}/trending_topics",
            params={"country_code": country_code,
                    "access_token": get_valid_token(brand)},
            timeout=20,
        )
        if not r.ok:
            logger.warning("trending_topics %s -> %s: %s",
                           country_code, r.status_code, r.text[:200])
            return []
        payload = r.json()
        return payload.get("data", payload) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("trending_topics %s failed: %s", country_code, exc)
        return []


def as_comment_targets(posts: list[dict], keyword: str,
                       own_handles: set[str] | None = None) -> list[dict]:
    """Shape API results into {prefix}_comment_targets rows.

    thread_id is the Graph media id, so these can be replied to via the API —
    `source='api'` is what tells the pipeline that.
    """
    own = {h.lower() for h in (own_handles or set())}
    rows = []
    for p in posts:
        user = (p.get("username") or "").lstrip("@")
        # Never reply to ourselves: cross-engagement between our own accounts
        # from one IP is a coordination signal.
        if not p.get("id") or not (p.get("text") or "").strip():
            continue
        if user.lower() in own or p.get("is_reply"):
            continue
        rows.append({
            "thread_id": p["id"],
            "username": user,
            "text": (p.get("text") or "").strip(),
            "url": p.get("permalink"),
            "keyword": keyword,
            "source": "api",
        })
    return rows


if __name__ == "__main__":
    import argparse
    import json

    from config.brands import get_brand

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Threads keyword search")
    ap.add_argument("--brand", default="tala")
    ap.add_argument("--q", default="ранкова рутина")
    ap.add_argument("--type", default="TOP", choices=["TOP", "RECENT"])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--check", action="store_true",
                    help="report whether threads_keyword_search is approved")
    ap.add_argument("--trending", metavar="COUNTRY", nargs="?", const="UA",
                    help="print trending topics for a country (default UA)")
    a = ap.parse_args()

    brand = get_brand(a.brand)

    if a.trending:
        # Accept a comma-separated list: Threads rolled Trending out per country,
        # so the useful question is which markets answer at all.
        codes = [c.strip().upper() for c in a.trending.split(",") if c.strip()]
        for code in codes:
            topics = trending_topics(brand, country_code=code, force=True)
            print(f"\n=== {code}: {len(topics)} тем ===")
            if topics:
                print(json.dumps(topics, ensure_ascii=False, indent=2)[:2500])
        raise SystemExit(0)
    posts = search(a.q, brand, search_type=a.type, limit=a.limit, force=True)

    if a.check:
        from config import settings
        own = {h.lower() for h in settings.OWN_HANDLES}
        others = [p for p in posts
                  if (p.get("username") or "").lower().lstrip("@") not in own]
        print(f"результатів: {len(posts)} | з них чужих авторів: {len(others)}")
        if not posts:
            print("НЕМАЄ ДОСТУПУ або порожня видача — див. лог вище.")
        elif not others:
            print("Дозвіл threads_keyword_search ЩЕ НЕ схвалено: "
                  "видача містить лише власні пости.")
        else:
            print("Дозвіл threads_keyword_search СХВАЛЕНО: видно чужі пости. "
                  "Можна відповідати через API, без браузера.")
        raise SystemExit(0)

    for p in posts:
        print(f"@{p.get('username')}  {p.get('id')}")
        print(f"  {(p.get('text') or '')[:110]}")
    print(f"\nвсього: {len(posts)}")
    if not posts:
        print(json.dumps({"hint": "перевір дозвіл: --check"}, ensure_ascii=False))

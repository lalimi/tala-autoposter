"""
Real Threads parser — no official API. Scrapes public Threads content with
Playwright using a saved login session, then extracts posts from the hidden JSON
the page ships in <script data-sjs> tags (the Scrapfly technique).

Two sources, one browser session:
  * keyword search   — what people post around a topic right now
  * tracked profiles — what the top-reach accounts in the niche are publishing

Ported from BlackSea viral-system/threads_scout.py. Public API:

    fetch_posts(keywords)          -> list[dict]   (keyword search)
    fetch_profile_posts(usernames) -> list[dict]   (those accounts' recent posts)
    fetch_all(keywords, usernames) -> {"keywords": [...], "profiles": [...]}

each dict: {"text", "source", "url", "keyword", "likes"} where for profile posts
`source` is the username and `keyword` is "@username".

ONE-TIME SETUP
--------------
    pip install playwright jmespath nested-lookup nest_asyncio
    playwright install chromium
    python -m parser.scraper --login      # opens a browser, log in manually

The login saves cookies to THREADS_SESSION_FILE (default: parser/scout_session.json).
On a headless VPS, run --login locally and copy that JSON file over. Session
cookies expire periodically — when scrapes start returning 0 posts, re-run --login.

Quick check:
    python -m parser.scraper --test "заробив вчора"
    python -m parser.scraper --profiles alex.meliaaa
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from parser.browser import proxy_launch_kwargs

# Where the Playwright cookie jar lives. Override with THREADS_SESSION_FILE.
_DEFAULT_SESSION = Path(__file__).parent / "scout_session.json"
# Fallback to the original viral-system session for local dev convenience.
_LEGACY_SESSION = (
    Path.home()
    / "Documents/Claude/Projects/BlackSea/viral-system/scout_session.json"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Cap how much we pull so one pipeline tick stays fast.
MAX_PER_SOURCE = 8
MAX_TOTAL = 20


def _session_file() -> Path:
    env = os.getenv("THREADS_SESSION_FILE")
    if env:
        return Path(env).expanduser()
    if _DEFAULT_SESSION.exists():
        return _DEFAULT_SESSION
    if _LEGACY_SESSION.exists():
        return _LEGACY_SESSION
    return _DEFAULT_SESSION


# ─────────────────────────────────────────────
# HIDDEN-JSON PARSING  (proven logic from threads_scout.py)
# ─────────────────────────────────────────────

def _extract_posts_from_html(html: str) -> list[dict]:
    """Pull posts out of Threads' embedded <script data-sjs> JSON blobs."""
    try:
        from nested_lookup import nested_lookup
    except ImportError:
        print("⚠️  pip install nested-lookup")
        return []

    posts: list[dict] = []
    pattern = r'<script type="application/json"[^>]*data-sjs[^>]*>(.*?)</script>'
    for script in re.findall(pattern, html, re.DOTALL):
        if '"ScheduledServerJS"' not in script or "thread_items" not in script:
            continue
        try:
            data = json.loads(script)
        except Exception:
            continue
        for thread_group in nested_lookup("thread_items", data):
            for item in thread_group:
                post = _parse_thread_item(item)
                if post:
                    posts.append(post)
    return posts


def _parse_thread_item(item: dict) -> dict | None:
    """Extract the fields we care about from one thread item."""
    try:
        post = item.get("post", item)
        text = (post.get("caption") or {}).get("text", "")
        if not text:
            return None
        username = (post.get("user") or {}).get("username", "")
        code = post.get("code", "")
        return {
            "text": text,
            "id": post.get("id", ""),
            "username": username,
            "likes": post.get("like_count", 0) or 0,
            "replies": (post.get("text_post_app_info") or {}).get(
                "direct_reply_count", 0
            )
            or 0,
            "url": (
                f"https://www.threads.net/@{username}/post/{code}" if code else ""
            ),
        }
    except Exception:
        return None


# ─────────────────────────────────────────────
# PLAYWRIGHT SCRAPE
# ─────────────────────────────────────────────

async def _load_session(context) -> bool:
    sf = _session_file()
    if not sf.exists():
        print(f"❌ No saved session at {sf}. Run: python -m parser.scraper --login")
        return False
    await context.add_cookies(json.loads(sf.read_text()))
    return True


async def _search_keyword(keyword: str, context) -> list[dict]:
    url = f"https://www.threads.net/search/?q={quote(keyword)}&serp_type=default"
    page = await context.new_page()
    try:
        # domcontentloaded, not networkidle: Threads keeps long-lived
        # connections open so networkidle routinely times out at 30s.
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        for _ in range(3):  # scroll to lazy-load more results
            await page.keyboard.press("End")
            await page.wait_for_timeout(1500)
        html = await page.content()
        return _extract_posts_from_html(html)[:MAX_PER_SOURCE]
    except Exception as e:
        print(f"⚠️  search '{keyword}' failed: {e}")
        return []
    finally:
        await page.close()


async def _scrape_profile(username: str, context) -> list[dict]:
    url = f"https://www.threads.net/@{username}"
    page = await context.new_page()
    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)
        await page.keyboard.press("End")  # one scroll for a few more posts
        await page.wait_for_timeout(1500)
        html = await page.content()
        return _extract_posts_from_html(html)[:MAX_PER_SOURCE]
    except Exception as e:
        print(f"⚠️  profile @{username} failed: {e}")
        return []
    finally:
        await page.close()


def _to_contract(post: dict, tag: str) -> dict:
    return {
        "text": post["text"].strip(),
        "source": post.get("username") or "threads.net",
        "url": post.get("url", ""),
        "keyword": tag,
        "likes": post.get("likes", 0),
        # Threads media id — needed to reply under this post (CommentAgent).
        "id": post.get("id", ""),
    }


async def _collect_async(
    keywords: list[str], usernames: list[str], max_total: int = MAX_TOTAL
) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("⚠️  pip install playwright && playwright install chromium")
        return {"keywords": [], "profiles": []}

    kw_posts: list[dict] = []
    prof_posts: list[dict] = []
    seen: set[str] = set()

    def _take(post: dict, tag: str, bucket: list[dict]) -> None:
        key = post.get("id") or post.get("text", "")[:60]
        if not key or key in seen:
            return
        seen.add(key)
        bucket.append(_to_contract(post, tag))

    # On a VPS running as root, set PLAYWRIGHT_NO_SANDBOX=1.
    launch_args = ["--no-sandbox"] if os.getenv("PLAYWRIGHT_NO_SANDBOX") else []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=launch_args, **proxy_launch_kwargs()
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900}, user_agent=UA
        )
        try:
            if not await _load_session(context):
                return {"keywords": [], "profiles": []}
            for kw in keywords:
                for post in await _search_keyword(kw, context):
                    _take(post, kw, kw_posts)
            for user in usernames:
                for post in await _scrape_profile(user, context):
                    _take(post, f"@{user}", prof_posts)
        finally:
            await browser.close()

    # strongest posts first by reach (likes)
    kw_posts.sort(key=lambda r: r.get("likes", 0), reverse=True)
    prof_posts.sort(key=lambda r: r.get("likes", 0), reverse=True)
    return {"keywords": kw_posts[:max_total], "profiles": prof_posts[:max_total]}


def _run(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # An event loop is already running (e.g. notebook / scheduler).
        import nest_asyncio  # type: ignore

        nest_asyncio.apply()
        return asyncio.get_event_loop().run_until_complete(coro)


def fetch_all(
    keywords: list[str], usernames: list[str], max_total: int = MAX_TOTAL
) -> dict:
    """One browser session, both sources. Returns {'keywords':[], 'profiles':[]}.

    Returns empty lists on any failure (missing deps, expired/absent session,
    network). `max_total` caps each list; the signal refresher raises it to keep
    broad keyword coverage.
    """
    keywords = keywords or []
    usernames = usernames or []
    if not keywords and not usernames:
        return {"keywords": [], "profiles": []}
    return _run(_collect_async(keywords, usernames, max_total))


def fetch_posts(keywords: list[str]) -> list[dict]:
    """Keyword search only — kept for the original ParserAgent contract."""
    return fetch_all(keywords, [])["keywords"]


def fetch_profile_posts(usernames: list[str]) -> list[dict]:
    """Recent posts from the given accounts, ranked by reach (likes)."""
    return fetch_all([], usernames)["profiles"]


# ─────────────────────────────────────────────
# CLI: --login / --test / --profiles
# ─────────────────────────────────────────────

async def _do_login() -> None:
    from playwright.async_api import async_playwright

    print("\n🔐 LOGIN MODE — a browser opens at threads.net. Log in, then press Enter.")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900}, user_agent=UA
        )
        page = await context.new_page()
        await page.goto("https://www.threads.net/login")
        input("\n⏳ Logged in? Press Enter to save the session...")
        cookies = await context.cookies()
        sf = _session_file()
        sf.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
        print(f"✅ Session saved: {sf} ({len(cookies)} cookies)")
        await browser.close()


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--login" in args:
        asyncio.run(_do_login())
    elif "--profiles" in args:
        users = [a for a in args if not a.startswith("--")] or ["alex.meliaaa"]
        results = fetch_profile_posts(users)
        for r in results:
            print(f"@{r['source']} ({r['likes']}♥): {r['text'][:90]!r}")
        print(f"\nTotal: {len(results)} posts")
    elif "--test" in args:
        kws = [a for a in args if not a.startswith("--")] or ["заробив вчора"]
        results = fetch_posts(kws)
        for r in results:
            print(f"[{r['keyword']}] @{r['source']} ({r['likes']}♥): {r['text'][:90]!r}")
        print(f"\nTotal: {len(results)} posts")
    else:
        print(__doc__)

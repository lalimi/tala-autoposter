"""Reply UNDER another user's post via the logged-in browser (Playwright).

The Threads Graph API can only reply to posts whose Graph media id you already
have (your own posts / mentions) — not arbitrary feed posts found by scraping.
So to comment on feed posts we drive the web UI with the scraper session.

Fragile by nature (Threads' DOM is obfuscated/localised) and higher ban-risk
than the API, so the caller keeps volume low (comment self-throttle). On every
attempt we save a screenshot to SHOT_PATH so selectors can be tuned from a real
page when something doesn't match.

    post_reply(url, text) -> bool   # True only if the reply is verified on-page
"""
from __future__ import annotations

import json
import os
import re

from parser.scraper import UA, _run, _session_file

SHOT_PATH = "/tmp/threads_reply.png"

# Threads localises labels; try EN/UA/RU.
REPLY_PLACEHOLDER = re.compile(r"Відповісти|Reply|Ответить", re.I)
POST_LABELS = ["Опублікувати", "Публікувати", "Post", "Надіслати", "Reply"]


async def _click_role(page, labels, timeout=4000) -> bool:
    for name in labels:
        try:
            await page.get_by_role("button", name=re.compile(f"^{name}$", re.I)).first.click(
                timeout=timeout
            )
            return True
        except Exception:
            continue
    return False


async def _open_composer(page) -> bool:
    """Focus the inline reply field. Try placeholder, then the visible
    'Відповісти користувачу…' text, then the expand affordance."""
    try:
        field = page.get_by_placeholder(REPLY_PLACEHOLDER).first
        await field.click(timeout=6000)
        return True
    except Exception:
        pass
    try:
        await page.get_by_text(REPLY_PLACEHOLDER).first.click(timeout=4000)
        return True
    except Exception:
        pass
    try:  # last resort: the first textbox that isn't search
        await page.get_by_role("textbox").last.click(timeout=4000)
        return True
    except Exception:
        return False


async def _post_reply_async(url: str, text: str) -> bool:
    from playwright.async_api import async_playwright

    launch_args = ["--no-sandbox"] if os.getenv("PLAYWRIGHT_NO_SANDBOX") else []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=launch_args)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900}, user_agent=UA
        )
        page = None
        try:
            sf = _session_file()
            if not sf.exists():
                print(f"⚠️  no scraper session at {sf}")
                return False
            await context.add_cookies(json.loads(sf.read_text()))
            page = await context.new_page()
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(4500)

            if not await _open_composer(page):
                print("⚠️  could not find the reply field")
                return False
            await page.wait_for_timeout(1000)

            # Type into whatever is now focused (the composer).
            await page.keyboard.type(text, delay=25)
            await page.wait_for_timeout(1000)

            if not await _click_role(page, POST_LABELS):
                await page.keyboard.press("Meta+Enter")
                await page.wait_for_timeout(400)
                await page.keyboard.press("Control+Enter")
            await page.wait_for_timeout(4000)

            # Verify: our text now renders on the page as a posted reply.
            try:
                posted = await page.get_by_text(text[:30], exact=False).count() > 0
            except Exception:
                posted = False
            if not posted:
                print("⚠️  reply not found on page after submit")
            return posted
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  browser reply failed: {exc}")
            return False
        finally:
            if page is not None:
                try:
                    await page.screenshot(path=SHOT_PATH)
                    print(f"📸 screenshot -> {SHOT_PATH}")
                except Exception:
                    pass
            await browser.close()


def post_reply(url: str, text: str) -> bool:
    """Publish `text` as a reply under the post at `url`. Best-effort; returns
    False on any failure (caller marks the target failed and moves on)."""
    if not url:
        return False
    return bool(_run(_post_reply_async(url, text)))

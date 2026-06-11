"""Reply UNDER another user's post via the logged-in browser (Playwright).

The Threads Graph API can only reply to posts whose Graph media id you already
have (your own posts / mentions) — not arbitrary feed posts found by scraping.
So to comment on feed posts we drive the web UI with the scraper session.

Fragile by nature (Threads' DOM is obfuscated/localised) and higher ban-risk
than the API, so the caller keeps volume low (comment self-throttle). On every
attempt we save a screenshot to SHOT_PATH so selectors can be tuned from a real
page when something doesn't match.

    post_reply(url, text) -> bool   # True only if we believe the reply posted
"""
from __future__ import annotations

import json
import os
import re

from parser.scraper import UA, _run, _session_file

SHOT_PATH = "/tmp/threads_reply.png"

# Threads localises labels; try EN/UA/RU.
REPLY_LABELS = ["Reply", "Відповісти", "Ответить"]
POST_LABELS = ["Post", "Опублікувати", "Публікувати", "Надіслати", "Ответить", "Post reply"]


async def _click_role(page, labels, timeout=4000) -> bool:
    for name in labels:
        try:
            await page.get_by_role("button", name=re.compile(name, re.I)).first.click(
                timeout=timeout
            )
            return True
        except Exception:
            continue
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

            # 1. open the reply composer (a button) — if there's already an inline
            #    textbox this may be a no-op, which is fine.
            await _click_role(page, REPLY_LABELS)
            await page.wait_for_timeout(1500)

            # 2. type into the first editable textbox.
            box = page.get_by_role("textbox").first
            await box.wait_for(timeout=8000)
            await box.click()
            await box.type(text, delay=25)  # human-ish typing
            await page.wait_for_timeout(1000)

            # 3. submit — try a Post button, then keyboard shortcuts.
            if not await _click_role(page, POST_LABELS):
                await page.keyboard.press("Meta+Enter")
                await page.wait_for_timeout(500)
                await page.keyboard.press("Control+Enter")
            await page.wait_for_timeout(3500)
            return True
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

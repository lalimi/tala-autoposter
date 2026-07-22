"""Pick a random image URL from a public manifest (e.g. a file on Cloudflare R2).

The manifest is any public URL whose body lists image URLs in one of:
  * a JSON array:            ["https://.../a.jpg", "https://.../b.png"]
  * a JSON object:           {"images": ["https://.../a.jpg", ...]}
  * plain text, one per line: https://.../a.jpg\nhttps://.../b.png

Failures are swallowed (returns None) so a broken/missing manifest never blocks
a post — it just publishes text-only. Manifests are cached briefly so a burst of
ticks doesn't re-fetch every time.
"""
from __future__ import annotations

import json
import logging
import random
import time

import requests

logger = logging.getLogger("tala")

_CACHE: dict[str, tuple[float, list[str]]] = {}
_TTL_SECONDS = 300


def _parse(body: str) -> list[str]:
    body = body.strip()
    urls: list[str] = []
    if body[:1] in "[{":
        data = json.loads(body)
        if isinstance(data, dict):
            data = data.get("images", [])
        urls = [str(u).strip() for u in data]
    else:
        urls = [ln.strip() for ln in body.splitlines()]
    # Keep only real http(s) links; drop blanks and comment lines.
    return [u for u in urls if u.startswith("http")]


def _load(manifest_url: str) -> list[str]:
    hit = _CACHE.get(manifest_url)
    if hit and time.time() - hit[0] < _TTL_SECONDS:
        return hit[1]
    r = requests.get(manifest_url, timeout=15)
    r.raise_for_status()
    urls = _parse(r.text)
    _CACHE[manifest_url] = (time.time(), urls)
    return urls


def pick_image(manifest_url: str, avoid: str | None = None) -> str | None:
    """Return a random image URL from the manifest, or None on any problem.
    `avoid` (e.g. the previous post's image) is skipped when possible so the
    same picture doesn't land on two posts in a row."""
    if not manifest_url:
        return None
    try:
        urls = _load(manifest_url)
    except Exception as exc:  # network / parse / HTTP error -> text-only post
        logger.warning("image manifest unreachable (%s): %s", manifest_url, exc)
        return None
    if not urls:
        logger.warning("image manifest empty: %s", manifest_url)
        return None
    choices = [u for u in urls if u != avoid] or urls
    return random.choice(choices)

"""Pick a random image URL from a manifest.

The manifest `source` is either a local file path (a list committed in the repo,
e.g. config/tala_images.txt) or a public URL (e.g. a file on Cloudflare R2). Its
body lists image URLs in one of:
  * a JSON array:            ["https://.../a.jpg", "https://.../b.png"]
  * a JSON object:           {"images": ["https://.../a.jpg", ...]}
  * plain text, one per line: https://.../a.jpg\nhttps://.../b.png

Failures are swallowed (returns None) so a broken/missing manifest never blocks
a post — it just publishes text-only. HTTP manifests are cached briefly so a
burst of ticks doesn't re-fetch every time.
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


def _load(source: str) -> list[str]:
    if source.startswith("http"):
        hit = _CACHE.get(source)
        if hit and time.time() - hit[0] < _TTL_SECONDS:
            return hit[1]
        r = requests.get(source, timeout=15)
        r.raise_for_status()
        urls = _parse(r.text)
        _CACHE[source] = (time.time(), urls)
        return urls
    # Local file (a list committed in the repo). Read fresh each time — it's cheap
    # and lets a redeploy pick up new URLs without a process restart.
    with open(source, encoding="utf-8") as f:
        return _parse(f.read())


def pick_image(source: str, avoid: str | None = None) -> str | None:
    """Return a random image URL from the manifest, or None on any problem.
    `source` is a local file path or an http(s) URL. `avoid` (e.g. the previous
    post's image) is skipped when possible so the same picture doesn't land on
    two posts in a row."""
    if not source:
        return None
    try:
        urls = _load(source)
    except Exception as exc:  # missing file / network / parse error -> text-only
        logger.warning("image manifest unreachable (%s): %s", source, exc)
        return None
    if not urls:
        logger.warning("image manifest empty: %s", manifest_url)
        return None
    choices = [u for u in urls if u != avoid] or urls
    return random.choice(choices)

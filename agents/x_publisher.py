"""Publisher for X (Twitter), mirroring PublisherAgent's interface so the
pipeline only has to pick a class.

Auth: OAuth 2.0 user context. POST /2/tweets rejects app-only bearer tokens, so
this needs a token the account itself authorised. Those expire in 2h and the
refresh token rotates on every refresh — agents/x_token_manager handles both and
persists the rotation, so the bot never needs a browser again.

Cost, since X bills per request (pay-per-use from Feb 2026): a plain post is
~$0.015, but a post containing a URL is ~$0.20 — 13x more. That is why
link-in-bio is both the reach-friendly AND the cheap option here.

Length: 280 chars without X Premium, up to 25 000 with it. The limit lives on the
Brand so a non-Premium account can't silently generate posts X will reject.
"""
from __future__ import annotations

import logging

import requests

from agents.x_token_manager import get_valid_x_token
from config.brands import Brand

logger = logging.getLogger("tala")

API = "https://api.x.com/2"
UPLOAD_URL = "https://upload.x.com/1.1/media/upload.json"


class XPublisher:
    def __init__(self, brand: Brand):
        self.brand = brand
        self.max_len = brand.max_post_chars

    def _headers(self) -> dict:
        return {"Authorization": "Bearer " + get_valid_x_token(self.brand.key)}

    def _check_len(self, text: str) -> None:
        if len(text) > self.max_len:
            raise ValueError(
                f"post is {len(text)} chars; limit for {self.brand.key} is "
                f"{self.max_len} (X Premium raises it to 25000)"
            )

    def publish(self, text: str, image_url: str | None = None) -> dict:
        self._check_len(text)
        pid = self._post(text, media_ids=self._upload(image_url))
        return {"post_id": pid, "parts": [pid], "raw": {"id": pid}}

    def publish_thread(self, parts: list[str], image_url: str | None = None) -> dict:
        """Post part 0, then each following part as a reply to the previous one —
        an X thread. The image (if any) goes on the first, feed-visible part."""
        parts = [p for p in parts if p and p.strip()]
        if not parts:
            raise ValueError("no parts to publish")
        for p in parts:
            self._check_len(p)

        ids: list[str] = []
        reply_to = None
        for i, p in enumerate(parts):
            pid = self._post(
                p, reply_to=reply_to,
                media_ids=self._upload(image_url) if i == 0 else None,
            )
            ids.append(pid)
            reply_to = pid
        return {"post_id": ids[0], "parts": ids, "raw": {"ids": ids}}

    def _post(self, text: str, reply_to: str | None = None,
              media_ids: list[str] | None = None) -> str:
        payload: dict = {"text": text}
        if reply_to:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
        r = requests.post(f"{API}/tweets", headers=self._headers(),
                          json=payload, timeout=30)
        if not r.ok:
            # Surface X's own error body — it names the cause (missing scope, no
            # credits, duplicate content) far better than the status code alone.
            raise RuntimeError(f"{r.status_code} on POST /2/tweets: {r.text[:300]}")
        pid = (r.json().get("data") or {}).get("id")
        if not pid:
            raise RuntimeError(f"X returned no post id: {r.text[:200]}")
        return str(pid)

    def _upload(self, image_url: str | None) -> list[str] | None:
        """X needs media uploaded to its own endpoint before it can be attached —
        a URL can't be passed through the way Threads allows. Best-effort: on any
        failure the post still goes out as text."""
        if not image_url:
            return None
        try:
            blob = requests.get(image_url, timeout=20)
            blob.raise_for_status()
            r = requests.post(UPLOAD_URL, headers=self._headers(),
                              files={"media": blob.content}, timeout=40)
            r.raise_for_status()
            mid = r.json().get("media_id_string")
            return [mid] if mid else None
        except Exception as exc:  # never block a post because of an image
            logger.warning("[%s] X image upload failed (%s) — posting text only",
                           self.brand.key, exc)
            return None

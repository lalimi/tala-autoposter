"""Publisher for X (Twitter), mirroring PublisherAgent's interface so the
pipeline only has to pick a class.

Auth: OAuth 1.0a user context (consumer key/secret + the account's access
token/secret). POST /2/tweets does NOT accept an app-only bearer token, and
OAuth 1.0a tokens don't expire — so unlike OAuth 2.0 there is no refresh dance
for a long-running bot.

Cost, since X bills per request (pay-per-use since Feb 2026): a plain post is
~$0.015, but a post containing a URL is ~$0.20 — 13x more. That is why
link-in-bio is both the reach-friendly AND the cheap option here; see
Brand.product_url usage in the writer.

Length: 280 chars without X Premium, up to 25 000 with it. The brand carries the
limit so a non-Premium account can't silently start failing.
"""
from __future__ import annotations

import logging

from config import settings
from config.brands import Brand

logger = logging.getLogger("tala")


class XPublisher:
    def __init__(self, brand: Brand):
        self.brand = brand
        self.max_len = brand.max_post_chars

    def _client(self):
        # Lazy import so brands that never touch X don't need tweepy installed.
        import tweepy

        creds = settings.x_credentials(self.brand.key)
        missing = [k for k, v in creds.items() if not v]
        if missing:
            raise RuntimeError(
                f"X credentials missing for {self.brand.key}: {', '.join(missing)}"
            )
        return tweepy.Client(
            consumer_key=creds["api_key"],
            consumer_secret=creds["api_secret"],
            access_token=creds["access_token"],
            access_token_secret=creds["access_secret"],
        )

    def _check_len(self, text: str) -> None:
        if len(text) > self.max_len:
            raise ValueError(
                f"post is {len(text)} chars; limit for {self.brand.key} is "
                f"{self.max_len} (X Premium raises it to 25000)"
            )

    def publish(self, text: str, image_url: str | None = None) -> dict:
        client = self._client()
        self._check_len(text)
        media_ids = self._upload(image_url)
        pid = self._post(client, text, media_ids=media_ids)
        return {"post_id": pid, "parts": [pid], "raw": {"id": pid}}

    def publish_thread(self, parts: list[str], image_url: str | None = None) -> dict:
        """Post part 0, then each following part as a reply to the previous one —
        an X thread. The image (if any) goes on the first, feed-visible part."""
        client = self._client()
        parts = [p for p in parts if p and p.strip()]
        if not parts:
            raise ValueError("no parts to publish")
        for p in parts:
            self._check_len(p)

        ids: list[str] = []
        reply_to = None
        for i, p in enumerate(parts):
            pid = self._post(
                client, p,
                reply_to=reply_to,
                media_ids=self._upload(image_url) if i == 0 else None,
            )
            ids.append(pid)
            reply_to = pid
        return {"post_id": ids[0], "parts": ids, "raw": {"ids": ids}}

    @staticmethod
    def _post(client, text: str, reply_to: str | None = None,
              media_ids: list[str] | None = None) -> str:
        kwargs: dict = {"text": text}
        if reply_to:
            kwargs["in_reply_to_tweet_id"] = reply_to
        if media_ids:
            kwargs["media_ids"] = media_ids
        resp = client.create_tweet(**kwargs)
        data = getattr(resp, "data", None) or {}
        pid = data.get("id")
        if not pid:
            raise RuntimeError(f"X create_tweet returned no id: {resp}")
        return str(pid)

    def _upload(self, image_url: str | None) -> list[str] | None:
        """X needs media uploaded to its own endpoint (v1.1) before it can be
        attached — a URL can't be passed through the way Threads allows.
        Best-effort: on any failure the post still goes out as text."""
        if not image_url:
            return None
        try:
            import io

            import requests
            import tweepy

            creds = settings.x_credentials(self.brand.key)
            auth = tweepy.OAuth1UserHandler(
                creds["api_key"], creds["api_secret"],
                creds["access_token"], creds["access_secret"],
            )
            blob = requests.get(image_url, timeout=20)
            blob.raise_for_status()
            media = tweepy.API(auth).media_upload(
                filename=image_url.rsplit("/", 1)[-1][:60] or "image.jpg",
                file=io.BytesIO(blob.content),
            )
            return [str(media.media_id)]
        except Exception as exc:  # never block a post because of an image
            logger.warning("[%s] X image upload failed (%s) — posting text only",
                           self.brand.key, exc)
            return None

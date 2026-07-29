"""Fetch a published X post's metrics, mirroring MetricsAgent's interface so
pipeline.run_metrics and store.save_metrics work unchanged.

  GET /2/tweets/{id}?tweet.fields=public_metrics,organic_metrics

X names things differently from Threads, so the numbers are mapped onto the same
keys the posts table already uses (views/likes/replies/reposts/quotes).
`impression_count` is the view count; it appears in organic_metrics for tweets
the authenticated account owns, and in public_metrics for the author too — read
both and prefer whichever is present.

Note this endpoint is a billed read (~$0.005) per post, which is why metrics are
collected once, ~24h after publishing, not polled.
"""
from __future__ import annotations

import requests

from agents.x_token_manager import get_valid_x_token
from config.brands import Brand

API = "https://api.x.com/2"

# X field -> our column
_MAP = {
    "impression_count": "views",
    "like_count": "likes",
    "reply_count": "replies",
    "retweet_count": "reposts",
    "quote_count": "quotes",
}


class XMetricsAgent:
    def __init__(self, brand: Brand):
        self.brand = brand

    def fetch(self, post_id: str) -> dict:
        token = get_valid_x_token(self.brand.key)
        r = requests.get(
            f"{API}/tweets/{post_id}",
            headers={"Authorization": "Bearer " + token},
            params={"tweet.fields": "public_metrics,organic_metrics"},
            timeout=20,
        )
        # organic_metrics needs extra scope on some apps; fall back to public.
        if r.status_code == 403:
            r = requests.get(
                f"{API}/tweets/{post_id}",
                headers={"Authorization": "Bearer " + token},
                params={"tweet.fields": "public_metrics"},
                timeout=20,
            )
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}

        out: dict[str, int] = {}
        # public first, then organic — organic wins where both exist since it is
        # the author-facing number.
        for block in ("public_metrics", "organic_metrics"):
            for x_name, value in (data.get(block) or {}).items():
                col = _MAP.get(x_name)
                if col is not None and value is not None:
                    out[col] = int(value)
        return out

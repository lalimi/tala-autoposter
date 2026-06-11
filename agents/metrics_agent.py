"""MetricsAgent — fetch a published post's insights from the Threads Graph API.

  GET /{media_id}/insights?metric=views,likes,replies,reposts,quotes

Threads returns each metric either as `total_value.value` or `values[0].value`
depending on the metric, so we read both shapes. Used ~24h after publishing so
the numbers have settled; the pipeline stores them and the writer learns from
the best performers.
"""
from __future__ import annotations

import requests

from agents.token_manager import get_valid_token
from config.brands import TALA, Brand

BASE_URL = "https://graph.threads.net/v1.0"
METRICS = ["views", "likes", "replies", "reposts", "quotes"]


class MetricsAgent:
    def __init__(self, brand: Brand = TALA):
        self.brand = brand

    def fetch(self, media_id: str) -> dict:
        token = get_valid_token(self.brand)
        r = requests.get(
            f"{BASE_URL}/{media_id}/insights",
            params={"metric": ",".join(METRICS), "access_token": token},
            timeout=20,
        )
        r.raise_for_status()
        out: dict[str, int] = {}
        for item in r.json().get("data", []):
            name = item.get("name")
            if name not in METRICS:
                continue
            val = item.get("total_value", {}).get("value")
            if val is None:
                values = item.get("values") or [{}]
                val = values[0].get("value")
            if val is not None:
                out[name] = int(val)
        return out

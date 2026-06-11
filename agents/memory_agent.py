"""Agent 3 — MemoryAgent: persistent state via Supabase (see store.py).
Topic rotation + post history so the system never repeats itself and can
reference what was published before. Thin wrapper over store.py so the rest of
the pipeline keeps the same interface it had with the old SQLite version.

Brand-aware: every call targets the brand's own {prefix}_posts table."""
from __future__ import annotations

import json

import store
from config.brands import TALA, Brand


class MemoryAgent:
    def __init__(self, brand: Brand = TALA, topics_file=None):
        self.brand = brand
        self.prefix = brand.table_prefix
        self.topics_file = topics_file or brand.topics_file

    def _topic_names(self) -> list[str]:
        with open(self.topics_file, encoding="utf-8") as f:
            return [t["name"] for t in json.load(f)["topics"]]

    def get_least_used_topic(self) -> str:
        return store.least_used_topic(self._topic_names(), prefix=self.prefix)

    def get_recent_topics(self, hours: int = 48) -> list[str]:
        return store.recent_topics(hours, prefix=self.prefix)

    def get_best_performing_post(self) -> str:
        # Best by views (learning); falls back to the latest post if no metrics.
        return store.best_post_by_metric(prefix=self.prefix)

    def recent_post_texts(self, limit: int = 12) -> list[str]:
        return store.recent_post_texts(prefix=self.prefix, limit=limit)

    def save_post(self, topic, fmt, text, postiz_id=None, status="draft") -> int:
        return store.save_post(topic, fmt, text, status, prefix=self.prefix)

    def mark_published(self, row_id, post_id, permalink=None):
        store.mark_published(row_id, post_id, permalink, prefix=self.prefix)

    def mark_failed(self, row_id):
        store.mark_failed(row_id, prefix=self.prefix)

    def recent_posts(self, limit: int = 10):
        return store.recent_posts(limit, prefix=self.prefix)

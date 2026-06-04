"""Agent 3 — MemoryAgent: persistent state via Supabase (see store.py).
Topic rotation + post history so the system never repeats itself and can
reference what was published before. Thin wrapper over store.py so the rest of
the pipeline keeps the same interface it had with the old SQLite version."""
from __future__ import annotations

import json

import store
from config import settings


class MemoryAgent:
    def __init__(self, topics_file=None):
        self.topics_file = topics_file or settings.TOPICS_FILE

    def _topic_names(self) -> list[str]:
        with open(self.topics_file, encoding="utf-8") as f:
            return [t["name"] for t in json.load(f)["topics"]]

    def get_least_used_topic(self) -> str:
        return store.least_used_topic(self._topic_names())

    def get_recent_topics(self, hours: int = 48) -> list[str]:
        return store.recent_topics(hours)

    def get_best_performing_post(self) -> str:
        # No analytics yet -> most recently published post as reference.
        return store.last_published_text()

    def save_post(self, topic, fmt, text, postiz_id=None, status="draft") -> int:
        return store.save_post(topic, fmt, text, status)

    def mark_published(self, row_id, post_id, permalink=None):
        store.mark_published(row_id, post_id, permalink)

    def mark_failed(self, row_id):
        store.mark_failed(row_id)

    def recent_posts(self, limit: int = 10):
        return store.recent_posts(limit)

"""Agent 3 — MemoryAgent: persistent SQLite state so the system never repeats
itself and can reference what was published before."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from config import settings


def _now() -> str:
    return datetime.utcnow().isoformat()


class MemoryAgent:
    def __init__(self, db_path=None, topics_file=None):
        self.db_path = str(db_path or settings.DB_PATH)
        self.topics_file = topics_file or settings.TOPICS_FILE
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                published_at DATETIME,
                topic TEXT,
                format TEXT,
                post_text TEXT,
                postiz_id TEXT,
                status TEXT
            );
            CREATE TABLE IF NOT EXISTS topic_rotation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT UNIQUE,
                last_used DATETIME,
                use_count INTEGER DEFAULT 0
            );
            """
        )
        self._conn.commit()
        self._seed_topics()

    def _seed_topics(self):
        """First-run population of topic_rotation from config/topics.json."""
        with open(self.topics_file, encoding="utf-8") as f:
            names = [t["name"] for t in json.load(f)["topics"]]
        for name in names:
            self._conn.execute(
                "INSERT OR IGNORE INTO topic_rotation (topic, last_used, use_count) "
                "VALUES (?, NULL, 0)",
                (name,),
            )
        self._conn.commit()

    def get_least_used_topic(self) -> str:
        """Topic not used in the last 24h, least used overall. Marks it used so
        the next run within 24h picks a different one."""
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        row = self._conn.execute(
            "SELECT topic FROM topic_rotation "
            "WHERE last_used IS NULL OR last_used < ? "
            "ORDER BY use_count ASC, last_used ASC LIMIT 1",
            (cutoff,),
        ).fetchone()
        if row is None:  # everything used in last 24h -> least used overall
            row = self._conn.execute(
                "SELECT topic FROM topic_rotation "
                "ORDER BY use_count ASC, last_used ASC LIMIT 1"
            ).fetchone()
        topic = row["topic"]
        self._conn.execute(
            "UPDATE topic_rotation SET last_used = ?, use_count = use_count + 1 "
            "WHERE topic = ?",
            (_now(), topic),
        )
        self._conn.commit()
        return topic

    def get_recent_topics(self, hours: int = 48) -> list[str]:
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        rows = self._conn.execute(
            "SELECT DISTINCT topic FROM posts "
            "WHERE published_at IS NOT NULL AND published_at >= ?",
            (cutoff,),
        ).fetchall()
        return [r["topic"] for r in rows]

    def get_best_performing_post(self) -> str:
        """No analytics yet -> use the most recently published post as reference."""
        row = self._conn.execute(
            "SELECT post_text FROM posts WHERE status = 'published' "
            "ORDER BY published_at DESC LIMIT 1"
        ).fetchone()
        return row["post_text"] if row else ""

    def save_post(self, topic, fmt, text, postiz_id, status) -> int:
        published_at = _now() if status == "published" else None
        cur = self._conn.execute(
            "INSERT INTO posts (published_at, topic, format, post_text, postiz_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (published_at, topic, fmt, text, postiz_id, status),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_post_status(self, postiz_id, status):
        self._conn.execute(
            "UPDATE posts SET status = ? WHERE postiz_id = ?", (status, postiz_id)
        )
        self._conn.commit()

    def mark_published(self, row_id, postiz_id):
        """Attach the Postiz id to the draft row and flip it to published."""
        self._conn.execute(
            "UPDATE posts SET postiz_id = ?, status = 'published', published_at = ? "
            "WHERE id = ?",
            (postiz_id, _now(), row_id),
        )
        self._conn.commit()

    def mark_failed(self, row_id):
        self._conn.execute(
            "UPDATE posts SET status = 'failed' WHERE id = ?", (row_id,)
        )
        self._conn.commit()

    def recent_posts(self, limit: int = 10):
        return self._conn.execute(
            "SELECT published_at, topic, status, post_text FROM posts "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

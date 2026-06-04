"""Agent 1 — ParserAgent: assemble a ResearchBrief from cached signals.

On Vercel there is no browser, so this agent does NOT scrape. It reads the
freshest signals from Supabase (tala_signals), which the decoupled browser
scraper (scripts/refresh_signals.py) keeps populated:
  * trend_signals — posts found by the topic's keywords
  * peer_signals  — recent posts from the tracked top-reach accounts (orientation
                    on viral structure/hooks/formats), ranked by reach."""
from __future__ import annotations

import json

import store
from config import settings


class ParserAgent:
    def __init__(self, topics_file=None):
        self.topics_file = topics_file or settings.TOPICS_FILE

    def _keywords_for(self, topic_name: str) -> list[str]:
        with open(self.topics_file, encoding="utf-8") as f:
            for topic in json.load(f)["topics"]:
                if topic["name"] == topic_name:
                    return topic["keywords"]
        return [topic_name]

    def run(self, topic_name: str) -> dict:
        """Return a ResearchBrief: {topic, keyword, trend_signals, peer_signals, angle}."""
        keywords = self._keywords_for(topic_name)

        signals = store.keyword_signals(keywords)
        while len(signals) < 3:
            signals.append(f"немає свіжих сигналів по темі: {topic_name}")

        peer_signals = store.peer_signals()

        keyword = keywords[0]
        angle = (
            f"показати на конкретних цифрах і деталях, як '{keyword}' "
            f"вплітається в щоденне життя тривожної людини"
        )
        return {
            "topic": topic_name,
            "keyword": keyword,
            "trend_signals": signals,
            "peer_signals": peer_signals,
            "angle": angle,
        }

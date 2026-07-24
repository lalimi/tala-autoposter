"""Agent 1 — ParserAgent: assemble a ResearchBrief from cached signals.

On Vercel there is no browser, so this agent does NOT scrape. It reads the
freshest signals from Supabase ({prefix}_signals), which the decoupled browser
scraper (scripts/refresh_signals.py) keeps populated:
  * trend_signals — posts found by the topic's keywords
  * peer_signals  — recent posts from the tracked top-reach accounts (orientation
                    on viral structure/hooks/formats), ranked by reach.

Brands without a scraper (e.g. @blacksea) simply have empty signal tables; the
brief then leans on the topic + the brand's angle, which is all an evergreen
platform post needs."""
from __future__ import annotations

import json

import store
from config.brands import TALA, Brand


class ParserAgent:
    def __init__(self, brand: Brand = TALA, topics_file=None):
        self.brand = brand
        self.prefix = brand.table_prefix
        self.topics_file = topics_file or brand.topics_file

    def _keywords_for(self, topic_name: str) -> list[str]:
        with open(self.topics_file, encoding="utf-8") as f:
            for topic in json.load(f)["topics"]:
                if topic["name"] == topic_name:
                    return topic["keywords"]
        return [topic_name]

    def run(self, topic_name: str) -> dict:
        """Return a ResearchBrief: {topic, keyword, trend_signals, peer_signals, angle}."""
        keywords = self._keywords_for(topic_name)

        signals = store.keyword_signals(keywords, prefix=self.prefix)
        while len(signals) < 3:
            signals.append(f"немає свіжих сигналів по темі: {topic_name}")

        peer_signals = store.peer_signals(prefix=self.prefix)
        # The single best real post on this topic — the writer translates/adapts
        # it. None until the scraper has populated this brand's signals.
        seed = store.top_seed(keywords, prefix=self.prefix)

        keyword = keywords[0]
        angle = self.brand.angle_template.format(keyword=keyword)
        return {
            "topic": topic_name,
            "keyword": keyword,
            "trend_signals": signals,
            "peer_signals": peer_signals,
            "seed": seed,
            "angle": angle,
        }

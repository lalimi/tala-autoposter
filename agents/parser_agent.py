"""Agent 1 — ParserAgent: gather raw content signals for the post.
Does NOT write the post — only collects material into a ResearchBrief.

Two signal sources:
  * trend_signals — posts found by the topic's keywords (what's circulating now)
  * peer_signals  — recent posts from the top-reach accounts we track in
                    config/accounts.json, ranked by reach, used as orientation
                    (what the niche leaders publish — themes, formats, hooks)."""
from __future__ import annotations

import json
import random

from config import settings
from parser.scraper import fetch_all  # no-API Threads scraper

ACCOUNTS_FILE = settings.CONFIG_DIR / "accounts.json"
# Scrape at most this many tracked accounts per run (random sample) so a long
# list stays fast and doesn't hammer Threads; coverage rotates across runs.
PEER_SAMPLE = 6


class ParserAgent:
    def __init__(self, topics_file=None, accounts_file=None):
        self.topics_file = topics_file or settings.TOPICS_FILE
        self.accounts_file = accounts_file or ACCOUNTS_FILE

    def _keywords_for(self, topic_name: str) -> list[str]:
        with open(self.topics_file, encoding="utf-8") as f:
            for topic in json.load(f)["topics"]:
                if topic["name"] == topic_name:
                    return topic["keywords"]
        return [topic_name]

    def _accounts(self) -> list[str]:
        try:
            with open(self.accounts_file, encoding="utf-8") as f:
                return json.load(f).get("accounts", [])
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def run(self, topic_name: str) -> dict:
        """Return a ResearchBrief: {topic, keyword, trend_signals, peer_signals, angle}."""
        keywords = self._keywords_for(topic_name)
        accounts = self._accounts()
        if len(accounts) > PEER_SAMPLE:
            accounts = random.sample(accounts, PEER_SAMPLE)

        data = fetch_all(keywords, accounts)
        results = data.get("keywords", [])
        peers = data.get("profiles", [])
        top = results[:5]

        signals = [r.get("text", "").strip()[:140] for r in top if r.get("text")][:3]
        while len(signals) < 3:
            signals.append(f"немає свіжих сигналів по темі: {topic_name}")

        # Top-reach accounts' posts as orientation, tagged with reach.
        peer_signals = [
            f"@{p['source']} ({p.get('likes', 0)}♥): {p.get('text', '').strip()[:130]}"
            for p in peers[:3]
        ]

        keyword = top[0].get("keyword") if top else keywords[0]
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

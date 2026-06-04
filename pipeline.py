"""Core pipeline — one post tick. No file logging or argparse here, so it imports
cleanly in BOTH the local scheduler (main.py) and the Vercel handler (api/cron.py).

MemoryAgent -> ParserAgent -> WriterAgent -> MemoryAgent -> PublisherAgent

Mostly publishes multi-post CHAINS (checklists / guides); occasionally a single
post. Controlled by settings.CHAIN_PROBABILITY.
"""
from __future__ import annotations

import logging
import random

from config import settings

logger = logging.getLogger("tala")


def run_pipeline(publish: bool = True) -> str:
    # Lazy imports so callers that only need part of the stack stay light.
    from agents.memory_agent import MemoryAgent
    from agents.parser_agent import ParserAgent
    from agents.writer_agent import WriterAgent

    memory = MemoryAgent()
    topic = memory.get_least_used_topic()
    logger.info("topic selected: %s", topic)

    brief = ParserAgent().run(topic)
    writer = WriterAgent()

    # Mostly chains (checklists/guides), occasional single posts.
    parts = None
    if random.random() < settings.CHAIN_PROBABILITY:
        parts = writer.run_chain(brief, memory)
        if len(parts) < 2:
            parts = None  # too short to be a chain -> fall back to a single post

    if parts:
        post_text = "\n\n---\n\n".join(parts)
        fmt = "chain"
    else:
        post_text = writer.run(brief, memory)
        fmt = "single"

    row_id = memory.save_post(topic, fmt, post_text, None, "draft")
    logger.info("draft | %s | %s | %s", fmt, topic, post_text[:60].replace("\n", " "))

    if not publish:
        logger.info("publish skipped (test/dry-run)")
        return post_text

    from agents.publisher_agent import PublisherAgent

    try:
        pub = PublisherAgent()
        result = pub.publish_thread(parts) if parts else pub.publish(post_text)
        post_id = result.get("post_id")
        memory.mark_published(row_id, post_id)
        logger.info(
            "published | %s | %s | id=%s | %d part(s)",
            fmt, topic, post_id, len(result.get("parts", [])),
        )
    except Exception as exc:  # never crash the scheduler / handler
        memory.mark_failed(row_id)
        logger.error("publish failed | %s | %s | %s | kept as draft", fmt, topic, exc)

    return post_text

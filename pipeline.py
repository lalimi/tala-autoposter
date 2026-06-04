"""Core pipeline — one post tick. No file logging or argparse here, so it imports
cleanly in BOTH the local scheduler (main.py) and the Vercel handler (api/cron.py).

MemoryAgent -> ParserAgent -> WriterAgent -> MemoryAgent -> PublisherAgent
"""
from __future__ import annotations

import logging

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
    post_text = WriterAgent().run(brief, memory)

    fmt = brief.get("format", "auto")
    row_id = memory.save_post(topic, fmt, post_text, None, "draft")
    logger.info("draft | %s | %s", topic, post_text[:60].replace("\n", " "))

    if not publish:
        logger.info("publish skipped (test/dry-run)")
        return post_text

    from agents.publisher_agent import PublisherAgent

    try:
        result = PublisherAgent().publish(post_text)
        post_id = result.get("post_id")
        memory.mark_published(row_id, post_id)
        logger.info(
            "published | %s | id=%s | %s",
            topic, post_id, post_text[:60].replace("\n", " "),
        )
    except Exception as exc:  # never crash the scheduler / handler
        memory.mark_failed(row_id)
        logger.error("publish failed | %s | %s | kept as draft", topic, exc)

    return post_text

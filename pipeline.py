"""Core pipeline — one post tick. No file logging or argparse here, so it imports
cleanly in BOTH the local scheduler (main.py) and the Vercel handlers
(api/cron.py for @tala.sav, api/blacksea.py for @blacksea).

MemoryAgent -> ParserAgent -> WriterAgent -> MemoryAgent -> PublisherAgent

Each run is driven by a Brand (voice, topics, tables, token, cadence). Tala
mostly publishes multi-post CHAINS (checklists / guides); blacksea mostly single
friendly posts. Controlled by brand.chain_probability.
"""
from __future__ import annotations

import logging
import random

from config.brands import TALA, Brand

logger = logging.getLogger("tala")


def run_pipeline(brand: Brand = TALA, publish: bool = True) -> str:
    # Lazy imports so callers that only need part of the stack stay light.
    from agents.memory_agent import MemoryAgent
    from agents.parser_agent import ParserAgent
    from agents.writer_agent import WriterAgent

    memory = MemoryAgent(brand)
    topic = memory.get_least_used_topic()
    logger.info("[%s] topic selected: %s", brand.key, topic)

    brief = ParserAgent(brand).run(topic)
    writer = WriterAgent(brand)

    # Chain vs single is brand-tuned (Tala leans chains, blacksea leans singles).
    parts = None
    if random.random() < brand.chain_probability:
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
    logger.info("[%s] draft | %s | %s | %s", brand.key, fmt, topic,
                post_text[:60].replace("\n", " "))

    if not publish:
        logger.info("[%s] publish skipped (test/dry-run)", brand.key)
        return post_text

    from agents.publisher_agent import PublisherAgent

    try:
        pub = PublisherAgent(brand)
        result = pub.publish_thread(parts) if parts else pub.publish(post_text)
        post_id = result.get("post_id")
        memory.mark_published(row_id, post_id)
        logger.info(
            "[%s] published | %s | %s | id=%s | %d part(s)",
            brand.key, fmt, topic, post_id, len(result.get("parts", [])),
        )
    except Exception as exc:  # never crash the scheduler / handler
        memory.mark_failed(row_id)
        logger.error("[%s] publish failed | %s | %s | %s | kept as draft",
                     brand.key, fmt, topic, exc)

    return post_text

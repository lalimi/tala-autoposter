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

# How many scraped candidates one comment tick may evaluate before giving up.
# Keyword noise means most get SKIPped, so a single-candidate tick would rarely
# land a comment.
COMMENT_CANDIDATES_PER_TICK = 5


def run_pipeline(
    brand: Brand = TALA, publish: bool = True, respect_min_gap: bool = False
) -> str | None:
    # Lazy imports so callers that only need part of the stack stay light.
    import store

    from agents.memory_agent import MemoryAgent
    from agents.parser_agent import ParserAgent
    from agents.writer_agent import WriterAgent

    # Self-throttle (cron path only): skip if the last post is too recent, so a
    # frequent cron + dropped/late GitHub runs still average the target cadence.
    if respect_min_gap and brand.min_gap_minutes:
        mins = store.minutes_since_last_post(brand.table_prefix)
        # Draw the gap fresh each tick so the spacing is never a fixed rhythm.
        gap = random.uniform(
            brand.min_gap_minutes,
            max(brand.max_gap_minutes, brand.min_gap_minutes),
        )
        if mins is not None and mins < gap:
            logger.info(
                "[%s] skip: last post %.0f min ago (< %.0f min, randomised)",
                brand.key, mins, gap,
            )
            return None

    memory = MemoryAgent(brand)
    topic = memory.get_least_used_topic()
    logger.info("[%s] topic selected: %s", brand.key, topic)

    brief = ParserAgent(brand).run(topic)
    writer = WriterAgent(brand)

    # Whether this post sells is decided HERE, not by the model: as an optional
    # nudge in the prompt the CTA showed up in 1 of 40 posts (2%).
    sell = bool(brand.product_url) and random.random() < brand.sales_probability
    # Point at the bio instead of pasting a URL for most sales posts on X: a post
    # with a link costs ~13x more there and gets less reach.
    via_bio = sell and random.random() < brand.bio_cta_ratio
    if sell:
        logger.info("[%s] sales post (CTA %s)", brand.key,
                    "-> bio" if via_bio else "-> link")

    # Pick the hook type here too: left to the model it always chose the income
    # reveal, so 447/94/60к opened most posts. Avoid the ones used most recently.
    # Cycle hooks by the hour rather than picking at random: the old exclusion
    # compared a hook's first word against recent openings, which never matched
    # (the "заборона/парадокс" hook writes "не показуй...", not "заборона"), so
    # in practice the same hook could run several posts in a row.
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # A brand may weight the rotation instead of taking every hook equally
    # often; the cycle holds indexes into HOOK_TYPES.
    if brand.hook_cycle:
        hook_index = brand.hook_cycle[now.hour % len(brand.hook_cycle)]
    else:
        hook_index = now.hour % len(writer.HOOK_TYPES)
    hook = writer.HOOK_TYPES[hook_index]
    # Rotate the grammar of the first line independently of the hook, on a
    # different stride, so the same hook doesn't keep producing the same
    # construction. 8 hooks x 8 forms with co-prime strides = long cycle.
    opening = writer.OPENING_FORMS[
        (now.hour * 3 + now.day) % len(writer.OPENING_FORMS)
    ]
    logger.info("[%s] hook: %s | opening: %s",
                brand.key, hook[:38], opening[:38])

    # Chain vs single is brand-tuned (Tala leans chains, blacksea leans singles),
    # except that a list hook needs the room: "ось 30 з них" cannot be delivered
    # in one 500-character post, and truncating it wastes the strongest format.
    parts = None
    force_chain = hook_index in writer.LIST_HOOK_INDEXES
    if force_chain or random.random() < brand.chain_probability:
        parts = writer.run_chain(brief, memory, sell=sell, hook=hook,
                                 via_bio=via_bio, opening=opening)
        if len(parts) < 2:
            parts = None  # too short to be a chain -> fall back to a single post

    if parts:
        post_text = "\n\n---\n\n".join(parts)
        fmt = "chain"
    else:
        post_text = writer.run(brief, memory, sell=sell, hook=hook,
                               via_bio=via_bio, opening=opening)
        fmt = "single"

    # Retire the fact so the next post reaches for different material.
    fact = brief.get("fact")
    if fact:
        store.mark_fact_used(fact["id"])
        logger.info("[%s] fact: %s", brand.key, fact["text"][:60])

    row_id = memory.save_post(topic, fmt, post_text, None, "draft")
    logger.info("[%s] draft | %s | %s | %s", brand.key, fmt, topic,
                post_text[:60].replace("\n", " "))

    if not publish:
        logger.info("[%s] publish skipped (test/dry-run)", brand.key)
        return post_text

    # Publisher depends on the network the brand posts to; both expose the same
    # publish()/publish_thread() interface.
    if brand.platform == "x":
        from agents.x_publisher import XPublisher as PublisherAgent
    else:
        from agents.publisher_agent import PublisherAgent

    # Maybe attach a random image from the brand's manifest (viral_dna: images
    # lift reach ~2.8x). Best-effort — a missing/broken manifest posts text-only.
    image_url = None
    if brand.image_manifest_url and random.random() < brand.image_probability:
        from agents.image_picker import pick_image

        image_url = pick_image(brand.image_manifest_url)
        if image_url:
            logger.info("[%s] attaching image | %s", brand.key, image_url)

    try:
        pub = PublisherAgent(brand)
        if parts:
            result = pub.publish_thread(parts, image_url=image_url)
        else:
            result = pub.publish(post_text, image_url=image_url)
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


def run_metrics(brand: Brand = TALA, **_) -> int:
    """Fetch + store insights for posts published >=24h ago that have none yet.
    Returns how many were updated. Never raises on a single post's failure."""
    import store

    if brand.platform == "x":
        from agents.x_metrics_agent import XMetricsAgent as MetricsAgent
    else:
        from agents.metrics_agent import MetricsAgent

    posts = store.posts_needing_metrics(brand.table_prefix)
    if not posts:
        logger.info("[%s] no posts need metrics", brand.key)
        return 0

    agent = MetricsAgent(brand)
    updated = 0
    for p in posts:
        try:
            m = agent.fetch(p["threads_post_id"])
            store.save_metrics(p["id"], m, brand.table_prefix)
            updated += 1
            logger.info("[%s] metrics | post %s | %s", brand.key, p["id"], m)
        except Exception as exc:  # one bad id shouldn't stop the batch
            logger.warning("[%s] metrics failed | post %s | %s",
                           brand.key, p["id"], exc)
            # A 400 here means the post is gone or too old for insights; it will
            # never succeed, so stamp it instead of retrying it on every run.
            if "400" in str(exc):
                store.save_metrics(p["id"], {}, brand.table_prefix)
                logger.info("[%s] post %s retired from the metrics queue",
                            brand.key, p["id"])
    return updated


def run_comment(
    brand: Brand = TALA, publish: bool = True, respect_min_gap: bool = False
) -> str | None:
    """One comment tick: reply under someone else's post (a scraped candidate).

    Returns the reply text, or None when skipped (throttled / disabled / no
    candidate). Never raises — a publish failure marks the target failed.
    """
    import store

    if not brand.comments_enabled:
        logger.info("[%s] comments disabled", brand.key)
        return None

    if respect_min_gap and brand.comment_min_gap_minutes:
        mins = store.minutes_since_last_comment(brand.table_prefix)
        # Randomise the gap (base..2x base) so spacing looks human, not robotic.
        base = brand.comment_min_gap_minutes
        gap = base + random.uniform(0, base)
        if mins is not None and mins < gap:
            logger.info("[%s] comment skip: last %.0f min ago (< %.0f, jittered)",
                        brand.key, mins, gap)
            return None

    from agents.writer_agent import WriterAgent

    # Keyword search is noisy (a "ставка" query pulls mortgage posts), so the
    # writer SKIPs anything off-niche or unkind. Walk a few candidates per tick
    # so heavy skipping doesn't mean the account never comments at all.
    writer = WriterAgent(brand)
    target, text = None, ""
    for _ in range(COMMENT_CANDIDATES_PER_TICK):
        candidate = store.next_comment_target(brand.table_prefix)
        if not candidate:
            logger.info("[%s] no comment targets (run the scraper)", brand.key)
            return None
        try:
            draft = writer.run_comment(candidate)
        except Exception as exc:
            # The target's own text goes into the prompt, and scraped posts
            # include war, politics and other material the model's content
            # filter rejects outright. That was killing the whole comment run —
            # and commenting is the only growth lever these accounts have.
            logger.info("[%s] candidate unusable (%s) -> @%s",
                        brand.key, str(exc)[:60], candidate.get("username"))
            store.mark_comment_failed(candidate["id"], brand.table_prefix)
            continue
        if draft and not draft.strip().upper().startswith("SKIP"):
            target, text = candidate, draft
            break
        logger.info("[%s] comment skipped by writer -> @%s",
                    brand.key, candidate.get("username"))
        store.mark_comment_failed(candidate["id"], brand.table_prefix)

    if not target:
        logger.info("[%s] no suitable comment target in %d candidates",
                    brand.key, COMMENT_CANDIDATES_PER_TICK)
        return None

    logger.info("[%s] comment draft -> @%s | %s",
                brand.key, target.get("username"), text[:60].replace("\n", " "))

    if not publish:
        return text

    # Comment via the browser: the Graph API can't reply to arbitrary feed posts
    # (we only have a scraped web id, not a Graph media id), so drive the web UI.
    try:
        from parser.commenter import post_reply

        # Comment as THIS brand: the reply is published by whoever the session
        # is logged in as. Without the brand's own session we'd silently reply
        # from another account, so refuse instead.
        session = brand.session_file
        if not session and brand is not TALA:
            logger.error("[%s] no session_file — refusing to comment from another "
                         "account's session", brand.key)
            return None

        ok = post_reply(target.get("url", ""), text, session_file=session or None)
        if ok:
            store.mark_commented(target["id"], None, text, brand.table_prefix)
            logger.info("[%s] commented | @%s | %s",
                        brand.key, target.get("username"), target.get("url"))
        else:
            store.mark_comment_failed(target["id"], brand.table_prefix)
            logger.error("[%s] comment not posted | @%s | %s (see screenshot)",
                         brand.key, target.get("username"), target.get("url"))
    except Exception as exc:  # never crash the handler
        store.mark_comment_failed(target["id"], brand.table_prefix)
        logger.error("[%s] comment failed | @%s | %s",
                     brand.key, target.get("username"), exc)

    return text

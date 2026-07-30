"""Gate scraped posts by niche relevance before they reach the writer.

Threads keyword search is loose: "погодинна ставка" returned a post about
mortgage rates, "premiere таймлайн" a political one. Those landed in
{prefix}_signals, and top_seed then handed them to the writer as the material to
adapt — so the highest-reach garbage shaped the post.

One cheap batched call scores candidates 0-10 for fit with the brand's niche; the
scraper keeps only those above the threshold. Only the top candidates by likes
are scored, since only those ever get picked as a seed anyway.
"""
from __future__ import annotations

import json
import logging
import re

from config import settings

logger = logging.getLogger("tala")

MIN_SCORE = 6          # below this a post is noise for the brand
MAX_TO_SCORE = 30      # only the strongest candidates are worth an LLM call


def _client():
    from anthropic import Anthropic

    kwargs = {"api_key": settings.WRITER_API_KEY}
    if settings.WRITER_BASE_URL:
        kwargs["base_url"] = settings.WRITER_BASE_URL
    return Anthropic(**kwargs)


def score_posts(niche: str, posts: list[dict]) -> dict[int, int]:
    """Map index -> score (0-10) for how well each post fits `niche`.
    On any failure returns {} so the caller keeps everything (fail-open: a noisy
    signal is better than no signal)."""
    if not posts:
        return {}
    listing = "\n".join(
        f"{i}. {(p.get('text') or '')[:220]}" for i, p in enumerate(posts)
    )
    prompt = (
        f"ніша акаунта: {niche}\n\n"
        "нижче пости, знайдені пошуком за ключовими словами. пошук неточний, "
        "тому частина постів не має до ніші жодного стосунку.\n\n"
        f"{listing}\n\n"
        "для КОЖНОГО поста поставь оцінку 0-10: наскільки він дотичний до ніші "
        "й наскільки з нього можна взяти робочий хук або структуру для поста в "
        "цій ніші.\n"
        "0-3 — чужа тема (нерухомість, політика, спорт, крипта, реклама чужих "
        "послуг, побутовий флуд без звʼязку з нішею)\n"
        "4-5 — дотичне здалеку\n"
        "6-10 — по темі, є що взяти\n\n"
        "поверни ЛИШЕ json-обʼєкт вигляду {\"0\": 7, \"1\": 2, ...} без пояснень."
    )
    try:
        client = _client()
        r = client.messages.create(
            model=settings.WRITER_MODEL,
            max_tokens=800,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(
            b.text for b in r.content if getattr(b, "type", "") == "text"
        ).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {}
        return {int(k): int(v) for k, v in json.loads(m.group(0)).items()}
    except Exception as exc:
        logger.warning("relevance scoring failed (%s) — keeping all posts", exc)
        return {}


def filter_relevant(niche: str, posts: list[dict]) -> list[dict]:
    """Keep the posts worth seeding from, best candidates first."""
    ranked = sorted(posts, key=lambda p: p.get("likes", 0) or 0, reverse=True)
    head, tail = ranked[:MAX_TO_SCORE], ranked[MAX_TO_SCORE:]
    scores = score_posts(niche, head)
    if not scores:
        return ranked  # scoring unavailable: change nothing
    kept = [p for i, p in enumerate(head) if scores.get(i, 10) >= MIN_SCORE]
    dropped = len(head) - len(kept)
    logger.info("relevance gate: kept %d of %d scored (dropped %d)",
                len(kept), len(head), dropped)
    # Unscored tail stays available but ranks below everything vetted.
    return kept + tail

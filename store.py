"""Supabase data layer (PostgREST over HTTP) — the single source of truth for
state, shared by the Vercel cron handler and the local/Mac scraper.

Per brand there are three tables, named by a prefix:
  {prefix}_posts   — history + topic rotation
  {prefix}_token   — auto-refreshed Threads token (single row, id=1)
  {prefix}_signals — scraped signals cache
e.g. tala_posts / blacksea_posts. Every function takes `prefix` (default
"tala") so callers select the brand's tables. All access uses the service_role
key, which bypasses RLS.

No SDK dependency — plain `requests`, so it runs unchanged on Vercel.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests

from config import settings

_BASE = f"{settings.SUPABASE_URL}/rest/v1"


# ── helpers ───────────────────────────────────────────────────────────────

def _headers(prefer: str | None = None) -> dict:
    key = settings.SUPABASE_SERVICE_KEY
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _req(method, table, params=None, json=None, prefer=None):
    if not settings.SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY not set")
    r = requests.request(
        method, f"{_BASE}/{table}",
        headers=_headers(prefer), params=params, json=json, timeout=20,
    )
    r.raise_for_status()
    return r.json() if r.text else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cutoff_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _iso_to_epoch(s: str) -> float:
    s = s.replace(" ", "T").replace("Z", "+00:00")
    # Python 3.10's fromisoformat wants exactly 3 or 6 fractional digits, but
    # Postgres trims trailing zeros (".51361" killed every job); pad to 6.
    s = re.sub(r"\.(\d{1,6})", lambda m: "." + m.group(1).ljust(6, "0"), s)
    return datetime.fromisoformat(s).timestamp()


def _epoch_to_iso(e: float) -> str:
    return datetime.fromtimestamp(e, tz=timezone.utc).isoformat()


def _in_list(values) -> str:
    def esc(v):
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "in.(" + ",".join(esc(v) for v in values) + ")"


# ── posts ─────────────────────────────────────────────────────────────────

def save_post(topic: str, fmt: str, text: str, status: str = "draft",
              prefix: str = "tala") -> int:
    published_at = _now_iso() if status == "published" else None
    row = _req(
        "POST", f"{prefix}_posts",
        json={"topic": topic, "format": fmt, "text": text,
              "status": status, "published_at": published_at},
        prefer="return=representation",
    )
    return row[0]["id"]


def mark_published(row_id: int, threads_post_id, permalink=None,
                   prefix: str = "tala") -> None:
    _req("PATCH", f"{prefix}_posts", params={"id": f"eq.{row_id}"},
         json={"status": "published", "threads_post_id": threads_post_id,
               "permalink": permalink, "published_at": _now_iso()},
         prefer="return=minimal")


def mark_failed(row_id: int, prefix: str = "tala") -> None:
    _req("PATCH", f"{prefix}_posts", params={"id": f"eq.{row_id}"},
         json={"status": "failed"}, prefer="return=minimal")


def recent_posts(limit: int = 10, prefix: str = "tala") -> list[dict]:
    return _req("GET", f"{prefix}_posts", params={
        "select": "published_at,topic,status,text,permalink",
        "order": "id.desc", "limit": limit,
    }) or []


def recent_topics(hours: int = 48, prefix: str = "tala") -> list[str]:
    rows = _req("GET", f"{prefix}_posts", params={
        "select": "topic", "status": "eq.published",
        "published_at": f"gte.{_cutoff_iso(hours)}",
    }) or []
    return list({r["topic"] for r in rows})


def minutes_since_last_post(prefix: str = "tala") -> float | None:
    """Minutes since this brand's most recent PUBLISHED post, or None if never.
    Used by the self-throttle so a dropped cron run is caught by the next one."""
    rows = _req("GET", f"{prefix}_posts", params={
        "select": "published_at", "status": "eq.published",
        "order": "published_at.desc", "limit": 1,
    }) or []
    if not rows or not rows[0].get("published_at"):
        return None
    return (datetime.now(timezone.utc).timestamp()
            - _iso_to_epoch(rows[0]["published_at"])) / 60


def last_published_text(prefix: str = "tala") -> str:
    rows = _req("GET", f"{prefix}_posts", params={
        "select": "text", "status": "eq.published",
        "order": "published_at.desc", "limit": 1,
    }) or []
    return rows[0]["text"] if rows else ""


def recent_post_texts(prefix: str = "tala", limit: int = 12, hours: int = 336) -> list[str]:
    """Recent published post texts — fed to the writer so it doesn't repeat
    itself (same stories, angles, phrasing)."""
    rows = _req("GET", f"{prefix}_posts", params={
        "select": "text", "status": "eq.published",
        "published_at": f"gte.{_cutoff_iso(hours)}",
        "order": "published_at.desc", "limit": limit,
    }) or []
    return [r["text"] for r in rows if r.get("text")]


# ── metrics (learning) ──────────────────────────────────────────────────────

def posts_needing_metrics(prefix: str = "tala", min_age_hours: int = 24,
                          limit: int = 12) -> list[dict]:
    """Published posts at least `min_age_hours` old that have no metrics yet."""
    return _req("GET", f"{prefix}_posts", params={
        "select": "id,threads_post_id",
        "status": "eq.published", "threads_post_id": "not.is.null",
        "metrics_at": "is.null",
        "published_at": f"lte.{_cutoff_iso(min_age_hours)}",
        "order": "published_at.desc", "limit": limit,
    }) or []


def save_metrics(post_id: int, m: dict, prefix: str = "tala") -> None:
    _req("PATCH", f"{prefix}_posts", params={"id": f"eq.{post_id}"},
         json={"views": m.get("views"), "likes": m.get("likes"),
               "replies": m.get("replies"), "reposts": m.get("reposts"),
               "quotes": m.get("quotes"), "metrics_at": _now_iso()},
         prefer="return=minimal")


def best_post_by_metric(prefix: str = "tala", days: int = 30) -> str:
    """Text of the best-performing recent post (by views), for the writer to
    learn from. Falls back to the most recent post if no metrics yet."""
    rows = _req("GET", f"{prefix}_posts", params={
        "select": "text,views,likes", "status": "eq.published",
        "metrics_at": "not.is.null",
        "published_at": f"gte.{_cutoff_iso(days * 24)}",
        "order": "views.desc.nullslast", "limit": 1,
    }) or []
    if rows and rows[0].get("text"):
        return rows[0]["text"]
    return last_published_text(prefix)


def least_used_topic(topics: list[str], prefix: str = "tala") -> str:
    """Least-recently-used topic from the config list (never-posted first)."""
    rows = _req("GET", f"{prefix}_posts", params={
        "select": "topic,created_at", "order": "created_at.desc", "limit": 200,
    }) or []
    last_idx: dict[str, int] = {}
    for i, r in enumerate(rows):  # smaller index = more recent
        last_idx.setdefault(r["topic"], i)
    never = [t for t in topics if t not in last_idx]
    if never:
        return never[0]
    return max(topics, key=lambda t: last_idx.get(t, 10 ** 9))


# ── token ─────────────────────────────────────────────────────────────────

def get_token(prefix: str = "tala") -> tuple[str | None, float | None]:
    rows = _req("GET", f"{prefix}_token",
                params={"select": "access_token,expires_at", "id": "eq.1"}) or []
    if not rows:
        return None, None
    return rows[0]["access_token"], _iso_to_epoch(rows[0]["expires_at"])


def save_token(token: str, expires_at_epoch: float, prefix: str = "tala") -> None:
    _req("POST", f"{prefix}_token", params={"on_conflict": "id"},
         json={"id": 1, "access_token": token,
               "expires_at": _epoch_to_iso(expires_at_epoch),
               "updated_at": _now_iso()},
         prefer="resolution=merge-duplicates,return=minimal")


# ── signals ───────────────────────────────────────────────────────────────

def keyword_signals(keywords: list[str], hours: int = 72, limit: int = 3,
                    prefix: str = "tala") -> list[str]:
    params = {"select": "text", "kind": "eq.keyword",
              "scraped_at": f"gte.{_cutoff_iso(hours)}",
              "order": "likes.desc", "limit": limit}
    if keywords:
        params["keyword"] = _in_list(keywords)
    rows = _req("GET", f"{prefix}_signals", params=params) or []
    return [r["text"].strip()[:140] for r in rows]


def peer_signals(hours: int = 72, limit: int = 3, prefix: str = "tala") -> list[str]:
    rows = _req("GET", f"{prefix}_signals", params={
        "select": "source,text,likes", "kind": "eq.peer",
        "scraped_at": f"gte.{_cutoff_iso(hours)}",
        "order": "likes.desc", "limit": limit,
    }) or []
    return [f"@{r['source']} ({r['likes']}♥): {r['text'].strip()[:130]}" for r in rows]


def replace_signals(kind: str, rows: list[dict], prefix: str = "tala") -> None:
    """Used by the scraper: clear this kind, insert the fresh batch."""
    _req("DELETE", f"{prefix}_signals", params={"kind": f"eq.{kind}"},
         prefer="return=minimal")
    if rows:
        _req("POST", f"{prefix}_signals", json=rows, prefer="return=minimal")


# ── comment targets ────────────────────────────────────────────────────────
# Candidates (other people's posts) to reply to. Populated by the scraper,
# consumed by the /api/comment endpoint. Upsert on thread_id so re-scraping
# never duplicates a row or resets one we've already commented on.

def save_comment_targets(rows: list[dict], prefix: str = "tala") -> None:
    """Insert fresh candidates; ignore ones we already have (by thread_id)."""
    rows = [r for r in rows if r.get("thread_id")]
    if not rows:
        return
    _req("POST", f"{prefix}_comment_targets",
         params={"on_conflict": "thread_id"},
         json=rows, prefer="resolution=ignore-duplicates,return=minimal")


def next_comment_target(prefix: str = "tala") -> dict | None:
    """Freshest un-commented candidate (most recently scraped)."""
    rows = _req("GET", f"{prefix}_comment_targets", params={
        "select": "id,thread_id,username,text,url,likes,keyword",
        "status": "eq.new", "order": "id.desc", "limit": 1,
    }) or []
    return rows[0] if rows else None


def mark_commented(target_id: int, reply_post_id, reply_text: str,
                   prefix: str = "tala") -> None:
    _req("PATCH", f"{prefix}_comment_targets", params={"id": f"eq.{target_id}"},
         json={"status": "commented", "reply_post_id": reply_post_id,
               "reply_text": reply_text, "commented_at": _now_iso()},
         prefer="return=minimal")


def mark_comment_failed(target_id: int, prefix: str = "tala") -> None:
    _req("PATCH", f"{prefix}_comment_targets", params={"id": f"eq.{target_id}"},
         json={"status": "failed"}, prefer="return=minimal")


def minutes_since_last_comment(prefix: str = "tala") -> float | None:
    rows = _req("GET", f"{prefix}_comment_targets", params={
        "select": "commented_at", "status": "eq.commented",
        "order": "commented_at.desc", "limit": 1,
    }) or []
    if not rows or not rows[0].get("commented_at"):
        return None
    return (datetime.now(timezone.utc).timestamp()
            - _iso_to_epoch(rows[0]["commented_at"])) / 60

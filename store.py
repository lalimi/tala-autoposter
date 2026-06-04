"""Supabase data layer (PostgREST over HTTP) — the single source of truth for
state, shared by the Vercel cron handler and the local/Mac scraper.

Tables: tala_posts (history + topic rotation), tala_token (auto-refreshed
Threads token), tala_signals (scraped signals cache). All access uses the
service_role key, which bypasses RLS.

No SDK dependency — plain `requests`, so it runs unchanged on Vercel.
"""
from __future__ import annotations

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
    return datetime.fromisoformat(s.replace(" ", "T")).timestamp()


def _epoch_to_iso(e: float) -> str:
    return datetime.fromtimestamp(e, tz=timezone.utc).isoformat()


def _in_list(values) -> str:
    def esc(v):
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "in.(" + ",".join(esc(v) for v in values) + ")"


# ── posts ─────────────────────────────────────────────────────────────────

def save_post(topic: str, fmt: str, text: str, status: str = "draft") -> int:
    published_at = _now_iso() if status == "published" else None
    row = _req(
        "POST", "tala_posts",
        json={"topic": topic, "format": fmt, "text": text,
              "status": status, "published_at": published_at},
        prefer="return=representation",
    )
    return row[0]["id"]


def mark_published(row_id: int, threads_post_id, permalink=None) -> None:
    _req("PATCH", "tala_posts", params={"id": f"eq.{row_id}"},
         json={"status": "published", "threads_post_id": threads_post_id,
               "permalink": permalink, "published_at": _now_iso()},
         prefer="return=minimal")


def mark_failed(row_id: int) -> None:
    _req("PATCH", "tala_posts", params={"id": f"eq.{row_id}"},
         json={"status": "failed"}, prefer="return=minimal")


def recent_posts(limit: int = 10) -> list[dict]:
    return _req("GET", "tala_posts", params={
        "select": "published_at,topic,status,text,permalink",
        "order": "id.desc", "limit": limit,
    }) or []


def recent_topics(hours: int = 48) -> list[str]:
    rows = _req("GET", "tala_posts", params={
        "select": "topic", "status": "eq.published",
        "published_at": f"gte.{_cutoff_iso(hours)}",
    }) or []
    return list({r["topic"] for r in rows})


def last_published_text() -> str:
    rows = _req("GET", "tala_posts", params={
        "select": "text", "status": "eq.published",
        "order": "published_at.desc", "limit": 1,
    }) or []
    return rows[0]["text"] if rows else ""


def least_used_topic(topics: list[str]) -> str:
    """Least-recently-used topic from the config list (never-posted first)."""
    rows = _req("GET", "tala_posts", params={
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

def get_token() -> tuple[str | None, float | None]:
    rows = _req("GET", "tala_token",
                params={"select": "access_token,expires_at", "id": "eq.1"}) or []
    if not rows:
        return None, None
    return rows[0]["access_token"], _iso_to_epoch(rows[0]["expires_at"])


def save_token(token: str, expires_at_epoch: float) -> None:
    _req("POST", "tala_token", params={"on_conflict": "id"},
         json={"id": 1, "access_token": token,
               "expires_at": _epoch_to_iso(expires_at_epoch),
               "updated_at": _now_iso()},
         prefer="resolution=merge-duplicates,return=minimal")


# ── signals ───────────────────────────────────────────────────────────────

def keyword_signals(keywords: list[str], hours: int = 72, limit: int = 3) -> list[str]:
    params = {"select": "text", "kind": "eq.keyword",
              "scraped_at": f"gte.{_cutoff_iso(hours)}",
              "order": "likes.desc", "limit": limit}
    if keywords:
        params["keyword"] = _in_list(keywords)
    rows = _req("GET", "tala_signals", params=params) or []
    return [r["text"].strip()[:140] for r in rows]


def peer_signals(hours: int = 72, limit: int = 3) -> list[str]:
    rows = _req("GET", "tala_signals", params={
        "select": "source,text,likes", "kind": "eq.peer",
        "scraped_at": f"gte.{_cutoff_iso(hours)}",
        "order": "likes.desc", "limit": limit,
    }) or []
    return [f"@{r['source']} ({r['likes']}♥): {r['text'].strip()[:130]}" for r in rows]


def replace_signals(kind: str, rows: list[dict]) -> None:
    """Used by the scraper: clear this kind, insert the fresh batch."""
    _req("DELETE", "tala_signals", params={"kind": f"eq.{kind}"},
         prefer="return=minimal")
    if rows:
        _req("POST", "tala_signals", json=rows, prefer="return=minimal")

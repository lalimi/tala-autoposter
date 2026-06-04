"""Keeps the Threads long-lived access token fresh.

Threads long-lived tokens last ~60 days and can be refreshed WITHOUT the app
secret via:

    GET https://graph.threads.net/refresh_access_token
        ?grant_type=th_refresh_token&access_token=<token>

…as long as the token is >24h old and not yet expired. Each refresh returns a
brand-new token good for another ~60 days.

We persist the live token and its expiry in data/threads_token.json (seeded from
.env's THREADS_ACCESS_TOKEN on first run). `get_valid_token()` is cheap — it only
hits the network when the token is within REFRESH_MARGIN_DAYS of expiry, which
then pushes expiry ~60 days out, so the next ~50 days of calls are offline.
"""
from __future__ import annotations

import json
import logging
import time

import requests

from config import settings

BASE_URL = "https://graph.threads.net"
TOKEN_STORE = settings.DATA_DIR / "threads_token.json"
REFRESH_MARGIN_DAYS = 10
DEFAULT_TTL_SECONDS = 60 * 24 * 3600  # assume 60d when the real expiry is unknown

logger = logging.getLogger("tala.token")


def _load_store() -> dict:
    if TOKEN_STORE.exists():
        try:
            return json.loads(TOKEN_STORE.read_text())
        except Exception:
            logger.warning("token store unreadable; reseeding from .env")
    return {}


def _save_store(token: str, expires_at: float) -> None:
    TOKEN_STORE.write_text(
        json.dumps({"access_token": token, "expires_at": expires_at}, indent=2)
    )


def _refresh(token: str) -> tuple[str, float]:
    """Exchange a long-lived token for a fresh one. Returns (token, expires_at)."""
    r = requests.get(
        f"{BASE_URL}/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": token},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    new_token = data["access_token"]
    expires_at = time.time() + int(data.get("expires_in", DEFAULT_TTL_SECONDS))
    return new_token, expires_at


def get_valid_token() -> str:
    """Return a usable token, refreshing in the background if it's near expiry."""
    store = _load_store()
    token = store.get("access_token") or settings.THREADS_ACCESS_TOKEN
    expires_at = store.get("expires_at")
    if not token:
        raise RuntimeError("no Threads token: set THREADS_ACCESS_TOKEN in .env")

    # First run (no store yet): refresh now to pin a known 60-day window.
    if not expires_at:
        try:
            token, expires_at = _refresh(token)
            logger.info(
                "threads token refreshed on first run; expires in %.0f days",
                (expires_at - time.time()) / 86400,
            )
        except Exception as exc:
            # Token may be <24h old (not yet refreshable) — assume 60d, retry later.
            expires_at = time.time() + DEFAULT_TTL_SECONDS
            logger.warning("initial token refresh failed: %s; assuming 60d", exc)
        _save_store(token, expires_at)
        return token

    # Refresh once we're inside the safety margin; otherwise stay offline.
    margin = REFRESH_MARGIN_DAYS * 24 * 3600
    if time.time() >= expires_at - margin:
        try:
            token, expires_at = _refresh(token)
            _save_store(token, expires_at)
            logger.info(
                "threads token refreshed; expires in %.0f days",
                (expires_at - time.time()) / 86400,
            )
        except Exception as exc:
            logger.error("token refresh failed: %s (using existing token)", exc)
    return token


def status() -> dict:
    store = _load_store()
    token = store.get("access_token") or settings.THREADS_ACCESS_TOKEN
    expires_at = store.get("expires_at")
    days_left = (expires_at - time.time()) / 86400 if expires_at else None
    return {
        "has_token": bool(token),
        "token_preview": (token[:10] + "…") if token else None,
        "expires_at": expires_at,
        "days_left": round(days_left, 1) if days_left is not None else None,
        "store_file": str(TOKEN_STORE),
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if "--refresh" in sys.argv[1:]:
        # Force a refresh regardless of margin (handy for testing / manual ops).
        store = _load_store()
        tok = store.get("access_token") or settings.THREADS_ACCESS_TOKEN
        new_tok, exp = _refresh(tok)
        _save_store(new_tok, exp)
        print(f"refreshed; expires in {(exp - time.time()) / 86400:.0f} days")
    print(json.dumps(status(), ensure_ascii=False, indent=2))

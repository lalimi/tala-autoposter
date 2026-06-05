"""Keeps the Threads long-lived access token fresh — stored in Supabase
(tala_token) so it survives serverless cold starts and is shared by Vercel and
any local run.

Threads long-lived tokens last ~60 days and refresh WITHOUT the app secret via:

    GET https://graph.threads.net/refresh_access_token
        ?grant_type=th_refresh_token&access_token=<token>

`get_valid_token()` is cheap — it only hits the refresh endpoint when the token
is within REFRESH_MARGIN_DAYS of expiry (then expiry jumps ~60 days out).
"""
from __future__ import annotations

import logging
import time

import requests

import store
from config import settings
from config.brands import TALA, Brand

BASE_URL = "https://graph.threads.net"
REFRESH_MARGIN_DAYS = 10
DEFAULT_TTL_SECONDS = 60 * 24 * 3600

logger = logging.getLogger("tala.token")


def _seed_token(brand: Brand) -> str:
    """The first-run token for a brand, read from its configured env var."""
    return getattr(settings, brand.seed_token_attr, "") or ""


def _refresh(token: str) -> tuple[str, float]:
    r = requests.get(
        f"{BASE_URL}/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": token},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    return data["access_token"], time.time() + int(
        data.get("expires_in", DEFAULT_TTL_SECONDS)
    )


def get_valid_token(brand: Brand = TALA) -> str:
    prefix = brand.table_prefix
    token, expires_at = store.get_token(prefix=prefix)
    if not token:  # first run: seed from env, pin a known window
        token = _seed_token(brand)
        if not token:
            raise RuntimeError(
                f"no Threads token in {prefix}_token or {brand.seed_token_attr}"
            )
        expires_at = None

    if not expires_at:
        try:
            token, expires_at = _refresh(token)
            logger.info("%s threads token refreshed (first run)", brand.key)
        except Exception as exc:
            expires_at = time.time() + DEFAULT_TTL_SECONDS
            logger.warning("initial token refresh failed: %s; assuming 60d", exc)
        store.save_token(token, expires_at, prefix=prefix)
        return token

    if time.time() >= expires_at - REFRESH_MARGIN_DAYS * 86400:
        try:
            token, expires_at = _refresh(token)
            store.save_token(token, expires_at, prefix=prefix)
            logger.info(
                "%s threads token refreshed; expires in %.0f days",
                brand.key, (expires_at - time.time()) / 86400,
            )
        except Exception as exc:
            logger.error("token refresh failed: %s (using existing token)", exc)
    return token


def status(brand: Brand = TALA) -> dict:
    token, expires_at = store.get_token(prefix=brand.table_prefix)
    days_left = (expires_at - time.time()) / 86400 if expires_at else None
    return {
        "brand": brand.key,
        "has_token": bool(token),
        "token_preview": (token[:10] + "…") if token else None,
        "days_left": round(days_left, 1) if days_left is not None else None,
    }


if __name__ == "__main__":
    import json
    import sys

    from config.brands import get_brand

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = sys.argv[1:]
    brand = TALA
    if "--brand" in args:
        brand = get_brand(args[args.index("--brand") + 1])
    if "--refresh" in args:
        tok, _ = store.get_token(prefix=brand.table_prefix)
        new_tok, exp = _refresh(tok or _seed_token(brand))
        store.save_token(new_tok, exp, prefix=brand.table_prefix)
        print(f"refreshed; expires in {(exp - time.time()) / 86400:.0f} days")
    print(json.dumps(status(brand), ensure_ascii=False, indent=2))

"""OAuth 2.0 token handling for X, with refresh.

X user tokens live 2 hours, so a long-running bot has to refresh. The refresh
token ROTATES on every refresh: the response carries a new refresh_token and the
old one dies immediately. Losing that value means the account has to be
re-authorised by hand in a browser — so the new pair is written to Supabase
(table `x_tokens`, one row per brand) before it is handed to the caller.

Env per brand: X_<BRAND>_CLIENT_ID / X_<BRAND>_CLIENT_SECRET.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone

import requests

import store
from config import settings

logger = logging.getLogger("tala")

TOKEN_URL = "https://api.x.com/2/oauth2/token"
# Refresh this long before the token actually dies, so a slow tick can't post
# with a token that expires mid-request.
REFRESH_MARGIN = timedelta(minutes=10)


def _row(brand_key: str) -> dict | None:
    rows = store._req("GET", "x_tokens", params={
        "select": "brand,access_token,refresh_token,expires_at",
        "brand": f"eq.{brand_key}", "limit": 1,
    }) or []
    return rows[0] if rows else None


def _save(brand_key: str, access: str, refresh: str, expires_in: int) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    store._req(
        "POST", "x_tokens",
        json=[{
            "brand": brand_key,
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }],
        prefer="resolution=merge-duplicates,return=minimal",
    )


def _refresh(brand_key: str, refresh_token: str) -> str:
    cid = settings._env(f"X_{brand_key.upper()}_CLIENT_ID")
    secret = settings._env(f"X_{brand_key.upper()}_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError(f"X client id/secret missing for {brand_key}")

    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    r = requests.post(
        TOKEN_URL,
        headers={"Authorization": "Basic " + basic,
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token,
              "client_id": cid},
        timeout=25,
    )
    if not r.ok:
        raise RuntimeError(f"X token refresh failed {r.status_code}: {r.text[:200]}")
    d = r.json()
    new_access, new_refresh = d.get("access_token"), d.get("refresh_token")
    if not new_access or not new_refresh:
        raise RuntimeError(f"X refresh response missing tokens: {d}")
    # Persist FIRST: the old refresh token is already dead at this point, so a
    # crash before saving would lock the account out.
    _save(brand_key, new_access, new_refresh, d.get("expires_in", 7200))
    logger.info("[%s] X token refreshed", brand_key)
    return new_access


def get_valid_x_token(brand_key: str) -> str:
    """A usable access token, refreshed if it is expired or about to be."""
    row = _row(brand_key)
    if not row:
        raise RuntimeError(
            f"no X token stored for '{brand_key}' — authorise the account once "
            "and seed the x_tokens table"
        )
    expires_at = store._iso_to_epoch(row["expires_at"])
    now = datetime.now(timezone.utc).timestamp()
    if now < expires_at - REFRESH_MARGIN.total_seconds():
        return row["access_token"]
    return _refresh(brand_key, row["refresh_token"])

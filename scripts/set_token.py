"""Replace a brand's Threads token — typed in hidden, never pasted into a chat.

A token only carries the permissions that were on the app when it was issued,
so adding threads_delete / threads_keyword_search / threads_profile_discovery
in the Meta dashboard changes nothing until a new token is generated there
(Use cases → Threads API → Settings → User Token Generator) and stored here:

    ssh -t tala 'cd tala-autoposter && .venv/bin/python -m scripts.set_token --brand blacksea'

The script refuses a token that belongs to a different account than the one
the brand currently posts as, so Tala's token cannot end up on blacksea.
"""
from __future__ import annotations

import argparse
import getpass
import time

import requests

import store
from agents.token_manager import BASE_URL, _refresh
from config.brands import get_brand

NEW_SCOPES = ("threads_delete", "threads_keyword_search", "threads_profile_discovery")


def _me(token: str) -> dict:
    r = requests.get(f"{BASE_URL}/v1.0/me", params={"fields": "id,username",
                                                    "access_token": token}, timeout=20)
    return r.json() if r.ok else {}


def _debug(token: str) -> dict:
    r = requests.get(f"{BASE_URL}/v1.0/debug_token",
                     params={"input_token": token, "access_token": token}, timeout=20)
    return (r.json() or {}).get("data") or {} if r.ok else {}


def main() -> None:
    ap = argparse.ArgumentParser(description="Store a new Threads token for a brand")
    ap.add_argument("--brand", required=True)
    brand = get_brand(ap.parse_args().brand)
    prefix = brand.table_prefix

    current, _ = store.get_token(prefix=prefix)
    current_user = (_me(current).get("username") if current else None)
    print(f"Бренд: {brand.key}. Зараз постить як: @{current_user or '?'}")

    token = getpass.getpass("Встав новий токен (символи не показуються): ").strip()
    me = _me(token)
    if not me.get("username"):
        raise SystemExit("Токен не працює: Threads його не прийняв. Нічого не змінено.")
    if current_user and me["username"].lower() != current_user.lower():
        raise SystemExit(f"Це токен @{me['username']}, а бренд {brand.key} постить як "
                         f"@{current_user}. Нічого не змінено.")

    scopes = _debug(token).get("scopes") or []
    print(f"Акаунт: @{me['username']}")
    print("Дозволи:", ", ".join(scopes) or "?")
    for s in NEW_SCOPES:
        print(f"  {s}: {'є' if s in scopes else 'НЕМАЄ'}")

    # Refresh to get a fresh ~60-day token and its real expiry. A short-lived
    # token can't be refreshed this way — storing it with a 60-day window would
    # break posting within the hour, so it is rejected instead.
    try:
        token, expires_at = _refresh(token)
    except Exception:
        exp = _debug(token).get("expires_at") or 0
        if exp and exp - time.time() > 7 * 86400:
            expires_at = float(exp)
        else:
            raise SystemExit("Це короткостроковий токен. Згенеруй довгостроковий у "
                             "User Token Generator і запусти знову. Нічого не змінено.")

    store.save_token(token, expires_at, prefix=prefix)
    days = (expires_at - time.time()) / 86400
    print(f"Збережено для {brand.key}. Діє ще {days:.0f} днів; далі система оновлює його сама.")


if __name__ == "__main__":
    main()

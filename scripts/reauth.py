"""Re-authorize a brand's Threads account so its token carries new permissions.

The dashboard's User Token Generator re-issues a token for what the account
has ALREADY granted. Adding threads_delete / threads_keyword_search /
threads_profile_discovery to the app does not reach existing grants — on
24.09.2026 a regenerated blacksea token came back with the same five old
permissions. Only a fresh consent through the Threads OAuth window adds them.

    ssh -t tala 'cd tala-autoposter && .venv/bin/python -m scripts.reauth --brand blacksea'

Needs REDIRECT_URI registered under Use cases → Threads API → Settings →
Redirect Callback URLs. The app secret is typed hidden and never stored. The
new token is saved only if it belongs to the same account and keeps every
permission the current one has: chains are published as replies, which need
threads_manage_replies, so a narrower token would silently break posting.
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import time
import urllib.parse

import requests

import store
from config import settings
from config.brands import get_brand

GRAPH = "https://graph.threads.net"
AUTHORIZE = "https://threads.net/oauth/authorize"
REDIRECT_URI = "https://lalimi.github.io/blacksea-privacy/callback.html"
# The Threads app id is public (it appears in every authorize URL).
APP_ID = getattr(settings, "THREADS_APP_ID", "") or "1672328520867855"
SCOPES = [
    "threads_basic", "threads_content_publish", "threads_manage_insights",
    "threads_manage_replies", "threads_read_replies",
    "threads_delete", "threads_keyword_search", "threads_profile_discovery",
]


def _scopes(token: str) -> set[str]:
    r = requests.get(f"{GRAPH}/v1.0/debug_token",
                     params={"input_token": token, "access_token": token}, timeout=20)
    return set(((r.json() or {}).get("data") or {}).get("scopes") or []) if r.ok else set()


def _username(token: str) -> str | None:
    r = requests.get(f"{GRAPH}/v1.0/me", params={"fields": "username",
                                                 "access_token": token}, timeout=20)
    return r.json().get("username") if r.ok else None


def _fail(what: str, r: requests.Response) -> None:
    # Meta's error body names the problem; it never contains our secret.
    raise SystemExit(f"{what}: HTTP {r.status_code} {r.text[:300]}\nНічого не змінено.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-authorize a brand with new permissions")
    ap.add_argument("--brand", required=True)
    brand = get_brand(ap.parse_args().brand)
    prefix = brand.table_prefix

    current, _ = store.get_token(prefix=prefix)
    user = _username(current) if current else None
    have = _scopes(current) if current else set()
    print(f"Бренд: {brand.key}, акаунт @{user or '?'}")

    url = AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": APP_ID, "redirect_uri": REDIRECT_URI, "scope": ",".join(SCOPES),
        "response_type": "code", "state": secrets.token_urlsafe(8),
    })
    print(f"\n1) Відкрий це посилання в браузері, де ти в Threads як @{user or '…'},"
          f" і натисни «Дозволити»:\n\n{url}\n")
    code = input("2) Встав код зі сторінки, що відкриється: ").strip().removesuffix("#_")
    secret = getpass.getpass("3) Встав секрет застосунку Threads (не показується): ").strip()

    r = requests.post(f"{GRAPH}/oauth/access_token", data={
        "client_id": APP_ID, "client_secret": secret, "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI, "code": code}, timeout=30)
    if not r.ok:
        _fail("Обмін коду не вдався", r)
    short = r.json()["access_token"]

    r = requests.get(f"{GRAPH}/access_token", params={
        "grant_type": "th_exchange_token", "client_secret": secret,
        "access_token": short}, timeout=30)
    if not r.ok:
        _fail("Не вдалося отримати довгостроковий токен", r)
    token = r.json()["access_token"]
    expires_at = time.time() + int(r.json().get("expires_in", 60 * 86400))

    new_user = _username(token)
    if user and (new_user or "").lower() != user.lower():
        raise SystemExit(f"Це авторизація @{new_user}, а бренд {brand.key} постить як "
                         f"@{user}. Нічого не змінено.")
    got = _scopes(token)
    print(f"\nАкаунт: @{new_user}\nДозволи: {', '.join(sorted(got))}")
    lost = have - got
    if lost:
        raise SystemExit(f"Новий токен втратив би: {', '.join(sorted(lost))} — "
                         "без них зламається постинг. Нічого не змінено.")
    store.save_token(token, expires_at, prefix=prefix)
    # Report the target permissions directly. Diffing against the old token is
    # unreliable: debug_token reports the account's current grant, so the old
    # token already shows the new permissions once consent is given.
    wanted = ("threads_delete", "threads_keyword_search", "threads_profile_discovery")
    print("Збережено. " + ", ".join(f"{s}: {'є' if s in got else 'НЕМАЄ'}" for s in wanted)
          + f". Діє {(expires_at - time.time()) / 86400:.0f} днів.")


if __name__ == "__main__":
    main()

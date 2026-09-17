"""Ask the Threads API itself which trending-topics endpoint exists.

Meta gates trending topics behind the `threads_trending_topics` App Review
permission ("access trending topics and related public content on Threads"), but
the endpoint path is not in the public docs — Buffer's trending feature was
built with the Threads team directly. Rather than guess in code, this probes the
plausible paths with a real token and prints what each one answers.

Read-only GETs, nothing is published. Run:

    python -m scripts.probe_trending --brand tala

Reading the output:
  200                     -> endpoint exists AND this token may call it
  400 / 403 + "permission"-> endpoint EXISTS, the app just lacks the permission
                             (that is the one to request in App Review)
  404 / "Unsupported"     -> no such path, ignore it
"""
from __future__ import annotations

import argparse
import json

import requests

from agents.token_manager import get_valid_token
from config.brands import get_brand

BASE = "https://graph.threads.net/v1.0"

# Plausible paths, ordered most to least likely.
CANDIDATES = [
    ("/trending_topics", {}),
    ("/me/trending_topics", {}),
    ("/trending", {}),
    ("/topics", {}),
    ("/trending_tags", {}),
    # Known-good control: proves the token and network are fine, and doubles as
    # the documented way to pull posts for a topic tag once you know its name.
    ("/keyword_search", {"q": "notion", "search_type": "TOP",
                         "search_mode": "TAG", "fields": "id,text,username"}),
]


def main() -> None:
    ap = argparse.ArgumentParser(description="probe Threads trending endpoints")
    ap.add_argument("--brand", default="tala")
    a = ap.parse_args()

    token = get_valid_token(get_brand(a.brand))
    print(f"{'endpoint':<24} {'code':<6} response")
    print("-" * 78)
    for path, extra in CANDIDATES:
        params = {"access_token": token, **extra}
        try:
            r = requests.get(f"{BASE}{path}", params=params, timeout=20)
            body = r.text[:220].replace("\n", " ")
            print(f"{path:<24} {r.status_code:<6} {body}")
        except Exception as exc:  # noqa: BLE001
            print(f"{path:<24} {'ERR':<6} {exc}")
    print()
    print(json.dumps({
        "200": "працює вже зараз",
        "400/403 з 'permission'": "ендпоінт Є — треба запросити дозвіл у App Review",
        "404 / Unsupported": "такого шляху немає",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

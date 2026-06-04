"""Agent 4 — PublisherAgent: publish directly to the Threads Graph API.

No Postiz. Two-step publish per Meta's Threads API:
  1. POST /me/threads (media_type=TEXT)            -> creation_id (a container)
  2. poll GET /{creation_id}?fields=status         until status == FINISHED
     (Meta needs a few seconds to process the container)
  3. POST /me/threads_publish (creation_id)        -> published post id

Auth: THREADS_ACCESS_TOKEN — a long-lived token for the @tala.sav account.
Threads text posts are capped at 500 characters.
"""
from __future__ import annotations

import time

import requests

from agents.token_manager import get_valid_token

BASE_URL = "https://graph.threads.net/v1.0"
MAX_LEN = 500


class PublisherAgent:
    def __init__(self):
        # Resolved at publish time so the scheduler picks up auto-refreshes.
        self.token = ""

    def publish(self, text: str) -> dict:
        self.token = get_valid_token()  # refreshes itself near expiry
        if len(text) > MAX_LEN:
            raise ValueError(f"post is {len(text)} chars; Threads limit is {MAX_LEN}")

        # 1. create the media container
        container = self._post("/me/threads", {"text": text, "media_type": "TEXT"})
        creation_id = container.get("id")
        if not creation_id:
            raise RuntimeError(f"container creation failed: {container}")

        # 2. wait until Meta finishes processing the container
        self._await_ready(creation_id)

        # 3. publish
        result = self._post("/me/threads_publish", {"creation_id": creation_id})
        return {
            "post_id": result.get("id"),
            "creation_id": creation_id,
            "raw": result,
        }

    def _await_ready(self, creation_id: str, timeout: int = 60) -> None:
        """Poll container status; raise on ERROR, return on FINISHED."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._get(f"/{creation_id}", {"fields": "status,error_message"})
            code = status.get("status")
            if code == "FINISHED":
                return
            if code == "ERROR":
                raise RuntimeError(f"container error: {status.get('error_message')}")
            time.sleep(5)
        # Timed out waiting — let the publish call surface any real error.

    def _get(self, endpoint: str, params: dict) -> dict:
        params["access_token"] = self.token
        r = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _post(self, endpoint: str, params: dict) -> dict:
        params["access_token"] = self.token
        r = requests.post(f"{BASE_URL}{endpoint}", params=params, timeout=20)
        r.raise_for_status()
        return r.json()

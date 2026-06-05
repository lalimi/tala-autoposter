"""Agent 4 — PublisherAgent: publish directly to the Threads Graph API.

No Postiz. Two-step publish per Meta's Threads API:
  1. POST /me/threads (media_type=TEXT)            -> creation_id (a container)
  2. poll GET /{creation_id}?fields=status         until status == FINISHED
     (Meta needs a few seconds to process the container)
  3. POST /me/threads_publish (creation_id)        -> published post id

Auth: a long-lived token for the target account, resolved per brand by
token_manager (the @tala.sav or @blacksea account).
Threads text posts are capped at 500 characters.
"""
from __future__ import annotations

import time

import requests

from agents.token_manager import get_valid_token
from config.brands import TALA, Brand

BASE_URL = "https://graph.threads.net/v1.0"
MAX_LEN = 500


class PublisherAgent:
    def __init__(self, brand: Brand = TALA):
        self.brand = brand
        # Resolved at publish time so the scheduler picks up auto-refreshes.
        self.token = ""

    def publish(self, text: str) -> dict:
        """Publish a single standalone post."""
        self.token = get_valid_token(self.brand)  # refreshes itself near expiry
        self._check_len(text)
        pid = self._publish_one(text)
        return {"post_id": pid, "parts": [pid], "raw": {"id": pid}}

    def publish_thread(self, parts: list[str]) -> dict:
        """Publish a reply-chain: post part 0, then each part as a reply to the
        previous one (Threads `reply_to_id`)."""
        self.token = get_valid_token(self.brand)
        parts = [p for p in parts if p and p.strip()]
        if not parts:
            raise ValueError("no parts to publish")
        for p in parts:
            self._check_len(p)

        ids: list[str] = []
        reply_to = None
        for p in parts:
            # Shorter per-part budget so a chain fits Vercel's 60s function cap.
            pid = self._publish_one(p, reply_to_id=reply_to, timeout=25, interval=2)
            ids.append(pid)
            reply_to = pid
        return {"post_id": ids[0], "parts": ids, "raw": {"ids": ids}}

    @staticmethod
    def _check_len(text: str) -> None:
        if len(text) > MAX_LEN:
            raise ValueError(f"post is {len(text)} chars; Threads limit is {MAX_LEN}")

    def _publish_one(
        self, text: str, reply_to_id: str | None = None,
        timeout: int = 45, interval: int = 3,
    ) -> str:
        params = {"text": text, "media_type": "TEXT"}
        if reply_to_id:
            params["reply_to_id"] = reply_to_id  # makes this post a reply -> chain
        container = self._post("/me/threads", params)
        creation_id = container.get("id")
        if not creation_id:
            raise RuntimeError(f"container creation failed: {container}")
        self._await_ready(creation_id, timeout, interval)
        result = self._post("/me/threads_publish", {"creation_id": creation_id})
        return result.get("id")

    def _await_ready(self, creation_id: str, timeout: int = 45, interval: int = 3) -> None:
        """Poll container status; raise on ERROR, return on FINISHED."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._get(f"/{creation_id}", {"fields": "status,error_message"})
            code = status.get("status")
            if code == "FINISHED":
                return
            if code == "ERROR":
                raise RuntimeError(f"container error: {status.get('error_message')}")
            time.sleep(interval)
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

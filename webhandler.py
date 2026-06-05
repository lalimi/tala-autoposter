"""Shared Vercel serverless handler — runs ONE post tick for a given brand.

Each brand gets a thin endpoint under api/ that just calls make_handler(brand):
  * api/cron.py     -> @tala.sav  (every 2h via GitHub Actions)
  * api/blacksea.py -> @blacksea  (3-4x/day via GitHub Actions)

Vercel Hobby crons only fire daily, so the real cadence comes from GitHub
Actions hitting these URLs (see .github/workflows/).

Security: set CRON_SECRET on Vercel; callers must send
`Authorization: Bearer <CRON_SECRET>`.

Required Vercel env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY,
CRON_SECRET. Per-brand Threads tokens live in Supabase ({prefix}_token).
"""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler


def make_handler(brand_key: str):
    """Build a BaseHTTPRequestHandler subclass bound to one brand."""

    class _Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def _run(self) -> None:
            secret = (os.getenv("CRON_SECRET") or "").strip()
            if secret and self.headers.get("Authorization") != f"Bearer {secret}":
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                from config.brands import get_brand
                from pipeline import run_pipeline

                text = run_pipeline(get_brand(brand_key), publish=True)
                self._send(200, {"ok": True, "brand": brand_key, "preview": text[:100]})
            except Exception as exc:  # noqa: BLE001
                # Log full detail server-side (Vercel logs); never echo it in the
                # response — tracebacks can contain secrets (e.g. the API key).
                logging.exception("pipeline failed (%s)", brand_key)
                self._send(500, {"ok": False, "error": type(exc).__name__})

        # External cron services use GET or POST — accept both.
        do_GET = _run
        do_POST = _run

    return _Handler

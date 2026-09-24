"""Retired Vercel serverless handler — answers 410 and runs nothing.

Production is the Hetzner VPS (deploy/systemd). This Vercel copy ran in
parallel with it from at least 12.07.2026 until 24.09.2026: GitHub Actions
called it every 30 minutes, it shared the Supabase tables and the Threads
tokens, and it deployed from main automatically. For Tala that meant 6-11 posts
a day instead of the planned cadence (the recovery cadence set on 17.09 never
took effect), 44 posts landing in near-simultaneous pairs as both schedulers
passed the same min-gap check, and 95 chains cut after their second part by
Vercel's 60-second function limit.

The GitHub workflows are gone, but Vercel still redeploys whatever is on main,
so the endpoints stay inert here rather than relying on the project being
deleted. Each api/ file must keep a real `class handler(...)` at module scope:
without it Vercel's Python builder finds no functions and the build fails —
which would leave the previous, still-posting deployment live.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler


class BaseBrandHandler(BaseHTTPRequestHandler):
    """Kept only so the api/ endpoints still build; every request gets 410."""

    brand_key = "tala"  # overridden by each api/ endpoint
    mode = "post"       # "post" | "comment"

    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def _run(self) -> None:
        self._send(410, {"ok": False, "brand": self.brand_key,
                         "error": "retired: production runs on Hetzner"})

    do_GET = _run
    do_POST = _run

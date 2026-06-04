"""Vercel serverless entry — runs ONE post tick per request.

Triggered every 2h by an external scheduler (GitHub Actions; see
.github/workflows/cron.yml). Vercel Hobby crons only fire daily, so the real
2-hour cadence comes from the GitHub Action.

Security: set the CRON_SECRET env var on Vercel; callers must send
`Authorization: Bearer <CRON_SECRET>`.

Required Vercel env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY,
CRON_SECRET. (The Threads token lives in Supabase tala_token.)
"""
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

# api/ is one level under the project root — make root modules importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)


class handler(BaseHTTPRequestHandler):
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
            from pipeline import run_pipeline

            text = run_pipeline(publish=True)
            self._send(200, {"ok": True, "preview": text[:100]})
        except Exception as exc:  # noqa: BLE001
            import traceback

            logging.exception("pipeline failed")
            self._send(500, {
                "ok": False,
                "error": str(exc),
                "type": type(exc).__name__,
                "cause": repr(getattr(exc, "__cause__", None))[:300],
                "trace": traceback.format_exc()[-1500:],
            })

    # External cron services use GET or POST — accept both.
    do_GET = _run
    do_POST = _run

"""Vercel serverless entry — one @tala.sav post tick per request.

Triggered every 2h by GitHub Actions (.github/workflows/cron.yml). See
webhandler.py for the shared logic, auth, and required env vars.
"""
import os
import sys

# api/ is one level under the project root — make root modules importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

from webhandler import BaseBrandHandler

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)


# Vercel detects this `class handler` statically — keep it an explicit class.
class handler(BaseBrandHandler):
    brand_key = "tala"

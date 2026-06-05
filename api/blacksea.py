"""Vercel serverless entry — one @blacksea post tick per request.

Triggered 3-4x/day by GitHub Actions (.github/workflows/blacksea-cron.yml). See
webhandler.py for the shared logic, auth, and required env vars.
"""
import os
import sys

# api/ is one level under the project root — make root modules importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

from webhandler import make_handler

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)

handler = make_handler("blacksea")

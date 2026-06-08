"""Vercel serverless entry — one @tala.sav COMMENT tick per request.

Replies under one scraped candidate post (other people's posts found by keyword;
see scripts/refresh_signals.py + {prefix}_comment_targets). Triggered by GitHub
Actions (.github/workflows/comment-cron.yml). See webhandler.py for shared logic.
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
    mode = "comment"

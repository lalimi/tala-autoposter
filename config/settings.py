"""Loads environment configuration and resolves project paths."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    """Read an env var and keep only its first line, trimmed.

    Tolerates dashboard paste mistakes (e.g. an extra line pasted into a
    secret field) that would otherwise smuggle a newline into an HTTP header
    and surface as httpx "Connection error.".
    """
    v = (os.getenv(name, default) or "").strip()
    return v.splitlines()[0].strip() if v else ""

# Paths
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
TOPICS_FILE = CONFIG_DIR / "topics.json"
DB_PATH = DATA_DIR / "memory.db"

# Anthropic (WriterAgent)
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
WRITER_MODEL = _env("WRITER_MODEL", "claude-sonnet-4-20250514")
WRITER_MAX_TOKENS = 400

# Share of runs that publish a multi-post CHAIN (checklist / guide) rather than
# a single post. Tala wants mostly chains, occasional singles. Tunable via env.
CHAIN_PROBABILITY = float(_env("CHAIN_PROBABILITY", "0.8") or "0.8")

# Threads Graph API (PublisherAgent) — publishes directly, no Postiz.
# Long-lived token for the @tala.sav account (60-day; refresh before expiry).
# Seeded into Supabase tala_token; this env var is only a first-run fallback.
THREADS_ACCESS_TOKEN = _env("THREADS_ACCESS_TOKEN")

# Supabase — single source of truth for state (posts, token, signals).
SUPABASE_URL = _env("SUPABASE_URL", "https://mukjpousdanernohanrt.supabase.co")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")

# Scheduler
POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", "1"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Local runtime dirs (best-effort: serverless filesystems are read-only).
for _d in (DATA_DIR, LOGS_DIR):
    try:
        _d.mkdir(exist_ok=True)
    except OSError:
        pass

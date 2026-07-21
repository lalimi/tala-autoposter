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

# Writer LLM. Primary: Kimi (Moonshot) via its Anthropic-compatible endpoint,
# so the anthropic SDK keeps working unchanged. If KIMI_API_KEY is unset we
# fall back to the direct Anthropic key so old deploys don't break.
KIMI_API_KEY = _env("KIMI_API_KEY")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
WRITER_API_KEY = KIMI_API_KEY or ANTHROPIC_API_KEY
WRITER_BASE_URL = _env(
    "WRITER_BASE_URL", "https://api.moonshot.ai/anthropic" if KIMI_API_KEY else ""
)
WRITER_MODEL = _env(
    "WRITER_MODEL", "kimi-k3" if KIMI_API_KEY else "claude-sonnet-5"
)
WRITER_MAX_TOKENS = 400

# Share of runs that publish a multi-post CHAIN (checklist / guide) rather than
# a single post. Tala wants mostly chains, occasional singles. Tunable via env.
CHAIN_PROBABILITY = float(_env("CHAIN_PROBABILITY", "0.9") or "0.9")

# Same knob for the @blacksea brand account, but flipped: mostly single friendly
# posts, only occasionally a short tips chain.
BLACKSEA_CHAIN_PROBABILITY = float(
    _env("BLACKSEA_CHAIN_PROBABILITY", "0.2") or "0.2"
)

# Self-throttle: the minimum minutes between published posts per brand. The cron
# fires often (every ~30 min) but the pipeline skips a tick if the last post is
# newer than this — so a dropped/delayed GitHub run is caught by the next one
# instead of leaving a gap. Tala ≈ every 2h; blacksea ≈ 3-4 posts across the day.
TALA_MIN_GAP_MINUTES = int(_env("POST_MIN_GAP_MINUTES", "115") or "115")
BLACKSEA_MIN_GAP_MINUTES = int(_env("BLACKSEA_MIN_GAP_MINUTES", "210") or "210")

# Commenting (replying under other people's posts). Only tala comments for now.
# Candidates are scraped by keyword (scripts/refresh_signals.py) into
# {prefix}_comment_targets; the /api/comment endpoint replies to the freshest one
# and self-throttles on this gap so it never spams.
TALA_COMMENT_MIN_GAP_MINUTES = int(
    _env("COMMENT_MIN_GAP_MINUTES", "90") or "90"
)

# Max posts per chain. Capped at 3 so a whole chain finishes inside Vercel's 60s
# function limit (each Threads publish round-trip is ~15s). On an always-on host
# (VPS) with no time cap, set CHAIN_MAX_PARTS=5 in the env for richer guides.
CHAIN_MAX_PARTS = int(_env("CHAIN_MAX_PARTS", "3") or "3")

# Threads Graph API (PublisherAgent) — publishes directly, no Postiz.
# Long-lived token for the @tala.sav account (60-day; refresh before expiry).
# Seeded into Supabase tala_token; this env var is only a first-run fallback.
THREADS_ACCESS_TOKEN = _env("THREADS_ACCESS_TOKEN")

# Long-lived token for the @blacksea brand account. Seeded into Supabase
# blacksea_token on first run; this env var is only the first-run fallback.
BLACKSEA_THREADS_ACCESS_TOKEN = _env("BLACKSEA_THREADS_ACCESS_TOKEN")

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

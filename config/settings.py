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
# Default to kimi-k2.6 with thinking OFF: ~4x cheaper output than k3 ($0.95/$4 vs
# $3/$15 per 1M) and no wasted reasoning tokens. Quality on short viral posts is
# on par with k3. Bump WRITER_MODEL=kimi-k3 in env if a harder task ever needs it.
WRITER_MODEL = _env(
    "WRITER_MODEL", "kimi-k2.6" if KIMI_API_KEY else "claude-sonnet-5"
)
WRITER_MAX_TOKENS = int(_env("WRITER_MAX_TOKENS", "800") or "800")

# Thinking budget (tokens the model may spend reasoning before the post). 0 =
# disabled — the cheapest setting and plenty for short posts. Raise it (e.g. 1024)
# only if you switch to a thinking model and want it to plan first.
WRITER_THINKING_BUDGET = int(_env("WRITER_THINKING_BUDGET", "0") or "0")

# Share of posts that MUST end with a product CTA + link. Left to the prompt as
# "optional", the model added the bridge in 1 of 40 posts (2%) — so the pipeline
# now decides and the writer is told it's mandatory for that post.
TALA_SALES_PROBABILITY = float(_env("TALA_SALES_PROBABILITY", "0.3") or "0.3")
DENYS_SALES_PROBABILITY = float(_env("DENYS_SALES_PROBABILITY", "0.3") or "0.3")

# Share of runs that publish a multi-post CHAIN (checklist / guide) rather than
# a single post. Tala wants mostly chains, occasional singles. Tunable via env.
CHAIN_PROBABILITY = float(_env("CHAIN_PROBABILITY", "0.9") or "0.9")

# Same knob for the @blacksea brand account, but flipped: mostly single friendly
# posts, only occasionally a short tips chain.
BLACKSEA_CHAIN_PROBABILITY = float(
    _env("BLACKSEA_CHAIN_PROBABILITY", "0.2") or "0.2"
)

# @denys — mostly short sarcastic single posts (curilka style), rare tips chain.
DENYS_CHAIN_PROBABILITY = float(
    _env("DENYS_CHAIN_PROBABILITY", "0.15") or "0.15"
)

# Self-throttle: the minimum minutes between published posts per brand. The cron
# fires often (every ~30 min) but the pipeline skips a tick if the last post is
# newer than this — so a dropped/delayed GitHub run is caught by the next one
# instead of leaving a gap. Tala ≈ every 2h; blacksea ≈ 3-4 posts across the day.
TALA_MIN_GAP_MINUTES = int(_env("POST_MIN_GAP_MINUTES", "115") or "115")
BLACKSEA_MIN_GAP_MINUTES = int(_env("BLACKSEA_MIN_GAP_MINUTES", "210") or "210")
# New-account warm-up: ~4h gap → 3-4 posts/day inside the daytime window. Lower
# to ~175 (≈ every 3h) once the account is a couple of weeks old and trusted.
DENYS_MIN_GAP_MINUTES = int(_env("DENYS_MIN_GAP_MINUTES", "240") or "240")

# Commenting (replying under other people's posts). Only tala comments for now.
# Candidates are scraped by keyword (scripts/refresh_signals.py) into
# {prefix}_comment_targets; the /api/comment endpoint replies to the freshest one
# and self-throttles on this gap so it never spams.
TALA_COMMENT_MIN_GAP_MINUTES = int(
    _env("COMMENT_MIN_GAP_MINUTES", "90") or "90"
)
# Denys is a brand-new account (days old, ~0 followers): browser automation from
# a fresh account is the highest-risk profile there is, so start deliberately
# slow — ~3 comments a day. Lower once the account has some history.
DENYS_COMMENT_MIN_GAP_MINUTES = int(
    _env("DENYS_COMMENT_MIN_GAP_MINUTES", "180") or "180"
)
# Denys's own browser cookie jar — replies are posted as whoever is logged in
# here, so this must be a session for @den.bilyy (NOT the scraper/Tala one).
DENYS_SESSION_FILE = _env(
    "DENYS_SESSION_FILE", str(BASE_DIR / "parser" / "denys_session.json")
)

# Images. A "manifest" lists image URLs — a JSON array, a {"images":[...]} object,
# or plain text with one URL per line. It can be a local file committed in the repo
# (default: config/tala_images.txt) or a public URL (e.g. a Cloudflare R2 file).
# The pipeline attaches a RANDOM image to a post with probability IMAGE_PROBABILITY.
# To add pictures: append their public URLs to config/tala_images.txt and push, or
# point TALA_IMAGE_MANIFEST_URL at a hosted manifest. Empty source = text-only.
TALA_IMAGE_MANIFEST_URL = _env(
    "TALA_IMAGE_MANIFEST_URL", str(CONFIG_DIR / "tala_images.txt")
)
# ~1 in 3 posts gets an image (viral_dna: image every ~3rd post, not every one).
TALA_IMAGE_PROBABILITY = float(_env("TALA_IMAGE_PROBABILITY", "0.35") or "0.35")
BLACKSEA_IMAGE_MANIFEST_URL = _env("BLACKSEA_IMAGE_MANIFEST_URL")
BLACKSEA_IMAGE_PROBABILITY = float(_env("BLACKSEA_IMAGE_PROBABILITY", "0") or "0")
# Denys posts real screenshots of his own screen, not random stock — so text-only
# by default. Set a manifest + probability later if he wants generic visuals.
DENYS_IMAGE_MANIFEST_URL = _env("DENYS_IMAGE_MANIFEST_URL")
DENYS_IMAGE_PROBABILITY = float(_env("DENYS_IMAGE_PROBABILITY", "0") or "0")

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

# Long-lived token for the @denys account. Seeded into Supabase denys_token on
# first run; this env var is only the first-run fallback.
DENYS_THREADS_ACCESS_TOKEN = _env("DENYS_THREADS_ACCESS_TOKEN")

# Our own Threads handles. Never comment under / treat as a peer signal one of
# our own accounts — cross-engagement from a single IP is a coordination flag.
OWN_HANDLES = {
    h.strip().lstrip("@").lower()
    for h in _env("OWN_HANDLES", "tala.sav,den.bilyy,blacksea.ua").split(",")
    if h.strip()
}

# X (Twitter), per brand: X_<BRAND>_CLIENT_ID / X_<BRAND>_CLIENT_SECRET.
# OAuth 2.0 user context — POST /2/tweets rejects app-only bearer tokens. The
# access/refresh tokens themselves live in Supabase (x_tokens), because the
# refresh token rotates on every refresh; see agents/x_token_manager.
def x_client_credentials(brand_key: str) -> dict:
    p = f"X_{brand_key.upper()}_"
    return {
        "client_id": _env(p + "CLIENT_ID"),
        "client_secret": _env(p + "CLIENT_SECRET"),
    }


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

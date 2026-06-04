"""Loads environment configuration and resolves project paths."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Paths
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
TOPICS_FILE = CONFIG_DIR / "topics.json"
DB_PATH = DATA_DIR / "memory.db"

# Anthropic (WriterAgent)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
WRITER_MODEL = os.getenv("WRITER_MODEL", "claude-sonnet-4-20250514")
WRITER_MAX_TOKENS = 400

# Threads Graph API (PublisherAgent) — publishes directly, no Postiz.
# Long-lived token for the @tala.sav account (60-day; refresh before expiry).
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN", "")

# Scheduler
POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", "1"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Make sure runtime directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

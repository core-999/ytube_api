"""Centralised configuration — all secrets and tunables in one place.

Values are read from environment variables. A local `.env` file is loaded
automatically at startup if present.
"""

import os

def load_dotenv(dotenv_path=".env"):
    if os.path.exists(dotenv_path):
        with open(dotenv_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key:
                        os.environ.setdefault(key, val)

# Load environment variables from .env file
load_dotenv()

# ── Telegram Bot ───────────────────────────────────────────────
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROUP = os.environ.get("TG_GROUP", "nub_coder_s")
CHANNEL = os.environ.get("TG_CHANNEL", "nub_coders")

admin_ids_str = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x) for x in admin_ids_str.split() if x.isdigit()]

# ── Redis ──────────────────────────────────────────────────────
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 15440))
REDIS_USERNAME = os.environ.get("REDIS_USERNAME", "default")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD")

# ── Rate Limits ────────────────────────────────────────────────
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", 1000))
ADMIN_LIMIT = int(os.environ.get("ADMIN_LIMIT", 10000))

"""
Secret settings (bot token, chat ID, API keys).

On your computer they come from the ".env" file in the project folder.
On GitHub Actions they come from GitHub Secrets (Phase 6).
They are NEVER written in the code.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent

# Read .env if it exists. Values already set in the environment (e.g. by
# GitHub Actions) are not overwritten.
load_dotenv(PROJECT_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
RELIEFWEB_APPNAME = os.getenv("RELIEFWEB_APPNAME", "").strip()

# Which database file to use. GitHub Actions uses the default,
# data/monitor.db (the "official" one, saved in the repository).
# On your computer, put MONITOR_DB=data/local.db in .env so your test runs
# never clash with the official database.
DB_FILE = PROJECT_DIR / os.getenv("MONITOR_DB", "data/monitor.db").strip()

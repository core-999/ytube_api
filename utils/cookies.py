"""Shared yt-dlp cookie handling.

One helper builds the cookie flags; `bootstrap()` exports browser cookies to
a file at startup and `start_refresh()` re-exports periodically so the file
stays valid as YouTube rotates tokens mid-session.
"""

import logging
import os
import subprocess
import threading
import time

from config import (
    COOKIES_FILE,
    COOKIES_BROWSER,
    COOKIES_BOOTSTRAP_URL,
    COOKIES_REFRESH_HOURS,
)

logger = logging.getLogger("yt_dlp_api.cookies")


def cookie_args(cookies: str | None = None) -> list[str]:
    """yt-dlp cookie flags — prefer the cookies file, fall back to browser."""
    path = cookies or COOKIES_FILE
    if path and os.path.exists(path):
        return ["--cookies", path]
    return ["--cookies-from-browser", COOKIES_BROWSER]


def _export() -> None:
    """Re-export the browser cookie jar into COOKIES_FILE.

    yt-dlp writes the cookie jar to `--cookies` after running, so pairing it
    with `--cookies-from-browser` persists the browser session to a file.
    """
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", COOKIES_BROWSER,
        "--cookies", COOKIES_FILE,
        "--skip-download",
        COOKIES_BOOTSTRAP_URL,
    ]
    logger.info(f"[COOKIES] Exporting {COOKIES_FILE} from {COOKIES_BROWSER}...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if os.path.exists(COOKIES_FILE):
            logger.info(f"[COOKIES] ✅ Wrote {COOKIES_FILE}")
        else:
            logger.error(f"[COOKIES] ❌ Export failed: {result.stderr.strip()[-300:]}")
    except Exception as e:
        logger.error(f"[COOKIES] ❌ Export error: {e}")


def bootstrap() -> None:
    """Export browser cookies into COOKIES_FILE once, at startup."""
    if os.path.exists(COOKIES_FILE):
        logger.info(f"[COOKIES] Using existing {COOKIES_FILE}")
        return
    _export()


def start_refresh() -> None:
    """Re-export cookies every COOKIES_REFRESH_HOURS in a daemon thread."""
    if COOKIES_REFRESH_HOURS <= 0:
        return

    def _loop():
        while True:
            time.sleep(COOKIES_REFRESH_HOURS * 3600)
            _export()

    threading.Thread(target=_loop, daemon=True).start()
    logger.info(f"[COOKIES] Refresh every {COOKIES_REFRESH_HOURS}h")


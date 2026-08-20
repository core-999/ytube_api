"""Shared yt-dlp cookie handling.

Cookies are strictly **optional** — extraction runs anonymously by default (see
`utils/ytdlp_runner.py`) and cookies are only a retry for age-gated/members-only
videos. So every helper here degrades quietly when no browser profile or cookie
file is available (containers, Railway, CI), instead of failing startup.

One helper builds the cookie flags; `bootstrap()` exports browser cookies to
a file at startup and `start_refresh()` re-exports periodically so the file
stays valid as YouTube rotates tokens mid-session.
"""

import logging
import os
import re
import subprocess
import threading
import time

from config import (
    COOKIES_FILE,
    COOKIES_BROWSER,
    COOKIES_BOOTSTRAP_URL,
    COOKIES_REFRESH_HOURS,
)

logger = logging.getLogger("ytube_api.cookies")

# Tri-state: None = never probed, True = export worked, False = no readable browser
# profile in this environment. Once we know it's False we stop passing
# --cookies-from-browser, so a failed anonymous resolve doesn't burn a second
# yt-dlp subprocess on a retry that cannot succeed.
_browser_available: bool | None = None


def browser_cookies_available() -> bool:
    """True unless a probe has proven no browser cookie jar is readable."""
    return _browser_available is not False


def _browsers() -> list[str]:
    """Configured browsers — COOKIES_BROWSER may list several (comma/space-separated)."""
    return [b for b in re.split(r"[,\s]+", COOKIES_BROWSER or "") if b]


def cookie_args(cookies: str | None = None) -> list[str]:
    """yt-dlp cookie flags — prefer a cookie file, fall back to the first browser.

    Returns `[]` when no cookie source exists; callers treat that as "stay
    anonymous" rather than an error.
    """
    path = cookies or COOKIES_FILE
    if path and os.path.exists(path):
        return ["--cookies", path]
    if not browser_cookies_available():
        return []
    browsers = _browsers()
    return ["--cookies-from-browser", browsers[0]] if browsers else []


def _export() -> bool:
    """Re-export the browser cookie jar into COOKIES_FILE.

    yt-dlp writes the cookie jar to `--cookies` after running, so pairing it
    with `--cookies-from-browser` persists the browser session to a file. Each
    configured browser is tried in order until one produces a valid file.

    Returns True on success. Failure is expected in containers with no browser
    profile and is *not* an error — it just pins the service to anonymous mode.
    """
    global _browser_available
    browsers = _browsers()
    if not browsers:
        logger.info("[COOKIES] No browser configured (COOKIES_BROWSER empty) — extracting anonymously")
        _browser_available = False
        return False
    errors: list[str] = []
    for browser in browsers:
        cmd = [
            "yt-dlp",
            "--cookies-from-browser", browser,
            "--cookies", COOKIES_FILE,
            "--skip-download",
            COOKIES_BOOTSTRAP_URL,
        ]
        logger.info(f"[COOKIES] Exporting {COOKIES_FILE} from {browser}...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except Exception as e:
            errors.append(f"{browser}: {e}")
            continue
        if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
            logger.info(f"[COOKIES] ✅ Wrote {COOKIES_FILE} from {browser}")
            _browser_available = True
            return True
        errors.append(f"{browser}: {result.stderr.strip()[-200:]}")
    _browser_available = False
    logger.warning(
        f"[COOKIES] No browser cookie jar available — continuing anonymously "
        f"(age-gated videos may fail). Details: {'; '.join(errors)}"
    )
    return False


def bootstrap() -> None:
    """Export browser cookies into COOKIES_FILE once, at startup (best effort)."""
    if os.path.exists(COOKIES_FILE):
        logger.info(f"[COOKIES] Using existing {COOKIES_FILE}")
        return
    _ = _export()


def start_refresh() -> None:
    """Re-export cookies every COOKIES_REFRESH_HOURS in a daemon thread."""
    if COOKIES_REFRESH_HOURS <= 0:
        return
    # Nothing to refresh if this environment has no readable browser profile.
    if not browser_cookies_available():
        logger.info("[COOKIES] Refresh disabled (no browser cookie jar)")
        return

    def _loop():
        while True:
            time.sleep(COOKIES_REFRESH_HOURS * 3600)
            _ = _export()

    threading.Thread(target=_loop, daemon=True).start()
    logger.info(f"[COOKIES] Refresh every {COOKIES_REFRESH_HOURS}h")


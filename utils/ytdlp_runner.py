"""Shared `yt-dlp -g` runner — the fallback for when the Innertube fast path can't resolve.

Anonymous FIRST, cookies only as a second attempt, because on YouTube today cookies
make ordinary videos *worse*, not better (all three measured on a normal video):
  * no cookies                        -> resolves fine
  * cookies + yt-dlp's default client -> "The page needs to be reloaded."
  * cookies + mweb (the only client   -> https formats need a GVS PO token, so
    that accepts cookies)                adaptive audio is dropped; 360p muxed survives

Cookies still earn their place on age-gated / members-only videos, which no
anonymous client can reach — so they run as a retry, not as the default. The retry
also relaxes the format selector, since the cookie-accepting client often offers
only the muxed stream and a hard selector would fail outright.

Both extraction call sites (cache_manager, media_extractor) route through here so
the client/cookie policy lives in exactly one place.
"""
import asyncio
import logging
import time

from utils.cookies import cookie_args
from utils.subprocess_limit import subprocess_slot

logger = logging.getLogger("ytube_api.ytdlp")

# The one client that accepts cookies without tripping YouTube's session check.
_COOKIE_CLIENTS = ["--extractor-args", "youtube:player_client=mweb,web_safari,tv"]


async def _run(url: str, selector: str, extra: list[str], timeout: int, tag: str) -> str | None:
    cmd = [
        "yt-dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        *extra,
        "-f", selector,
        "--no-playlist",
        "-g",
        url,
    ]
    start = time.time()
    try:
        async with subprocess_slot:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"[{tag}] TIMEOUT after {timeout}s")
        return None
    except Exception as e:
        logger.error(f"[{tag}] Exception: {e}")
        return None

    elapsed = round(time.time() - start, 2)
    if process.returncode == 0 and stdout:
        logger.info(f"[{tag}] ✅ ({elapsed}s)")
        return stdout.decode().strip().split("\n")[0]

    err = stderr.decode().strip() if stderr else "no stderr"
    logger.error(f"[{tag}] ❌ exit={process.returncode} ({elapsed}s): {err[-300:]}")
    return None


async def resolve_g(url: str, selector: str, cookies: str | None = None,
                    timeout: int = 40, tag: str = "YT-DLP") -> str | None:
    """Resolve one stream URL: anonymous attempt, then a cookie attempt if that fails."""
    stream_url = await _run(url, selector, [], timeout, f"{tag}/anon")
    if stream_url:
        return stream_url

    cargs = cookie_args(cookies)
    if not cargs:
        # No cookie jar in this environment (e.g. container with no browser
        # profile) — anonymous was the only possible attempt.
        return None
    # ponytail: trailing /best so an age-gated video still yields its muxed stream
    # instead of failing the selector when adaptive formats are withheld.
    return await _run(url, f"{selector}/best", [*cargs, *_COOKIE_CLIENTS],
                      timeout, f"{tag}/cookies")

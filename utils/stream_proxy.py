"""Byte-proxy for googlevideo URLs — the only way an off-box client can play them.

googlevideo signs the extracting host's IP into the URL (`ip` sits inside the signed
`sparams`), so a link resolved on this server plays ONLY from this server. Any other
network — a browser at home, a phone, another datacenter — gets HTTP 403. That is true
of every extraction path (Innertube and `yt-dlp -g` produce the same lock), so it can't
be fixed by changing extractor: the bytes have to leave from the IP that fetched them.

Redirecting stays the right call for same-box consumers (the Telegram bot), which pay
no bandwidth for it. This module is for everyone else.

`Range` is forwarded in both directions so players can seek and browsers can start
mid-file instead of pulling the whole thing.
"""
import logging

import httpx
from fastapi.responses import StreamingResponse

logger = logging.getLogger("yt_dlp_api.proxy")

# Generous read timeout: googlevideo throttles long transfers, and a slow chunk is
# normal rather than a failure. Connect stays short so a dead CDN node fails fast.
_client = httpx.AsyncClient(
    timeout=httpx.Timeout(10.0, read=120.0),
    follow_redirects=True,
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
)

# Only headers a media player actually needs; hop-by-hop ones must not be copied.
_PASS_THROUGH = ("content-type", "content-length", "content-range", "accept-ranges")

_CHUNK = 65536


async def proxy_stream(url: str, range_header: str | None = None) -> StreamingResponse | None:
    """Stream `url` through this host, or None if the CDN rejected it.

    Returning None (rather than raising) lets the caller answer 502 with its own
    shape, matching the other endpoints.
    """
    headers = {"Range": range_header} if range_header else {}
    try:
        req = _client.build_request("GET", url, headers=headers)
        upstream = await _client.send(req, stream=True)
    except Exception as e:
        logger.error(f"[PROXY] upstream connect failed: {e}")
        return None

    if upstream.status_code >= 400:
        logger.error(f"[PROXY] upstream {upstream.status_code} (expired or IP-locked URL)")
        await upstream.aclose()
        return None

    async def body():
        # finally, not a plain close: the client hanging up raises inside the
        # generator, and without this the connection would leak from the pool.
        try:
            async for chunk in upstream.aiter_bytes(_CHUNK):
                yield chunk
        finally:
            await upstream.aclose()

    out = {k: v for k, v in upstream.headers.items() if k.lower() in _PASS_THROUGH}
    out.setdefault("accept-ranges", "bytes")  # lowercase: upstream keys are too, so no dupe
    return StreamingResponse(body(), status_code=upstream.status_code, headers=out)


async def close_client() -> None:
    await _client.aclose()

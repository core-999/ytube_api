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

This is the single proxy implementation — `main.py` routes delegate here. It used to
have a near-duplicate copy inline, which is how the two drifted apart (one had a
per-request client, the other a shared one; one decompressed while forwarding the
compressed length).
"""
import asyncio
import logging
import time
from typing import AsyncIterator, Optional

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.responses import Response

from utils import metrics

logger = logging.getLogger("ytube_api.proxy")

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Only headers a media player actually needs; hop-by-hop ones must not be copied.
# `content-encoding` is included because we forward the body verbatim (aiter_raw) —
# dropping it while keeping the compressed bytes would corrupt the stream.
_PASS_THROUGH = (
    "content-type",
    "content-length",
    "content-range",
    "content-encoding",
    "accept-ranges",
    "content-disposition",
    "cache-control",
)

_CHUNK = 128 * 1024

# Read timeout is generous but finite: googlevideo throttles long transfers and a slow
# chunk is normal, but `read=None` (the old inline copy) meant a silently dead socket
# hung the player forever instead of erroring. Connect stays short so a dead CDN node
# fails fast.
_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=30.0)

# Media transfers are long-lived, so the pool needs room for concurrent viewers.
# Keepalive is small: per-session CDN hosts are rarely reused.
_LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=20, keepalive_expiry=30.0)

_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """Lazily created shared client (built inside the running loop, not at import)."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            limits=_LIMITS,
            # HTTP/1.1 on purpose: googlevideo media is a single large body per
            # connection, so h2 multiplexing buys nothing and adds flow-control
            # stalls on big transfers.
            http2=False,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _upstream_headers(range_header: Optional[str], user_agent: Optional[str]) -> dict:
    headers = {
        "user-agent": user_agent or _DEFAULT_UA,
        # We forward bytes verbatim and forward `content-length` verbatim with them,
        # so never let httpx negotiate a transfer encoding it would transparently
        # decode — the length would then describe the compressed body and the client
        # would see a truncated or hanging stream.
        "accept-encoding": "identity",
    }
    if range_header:
        headers["range"] = range_header
    return headers


async def proxy_stream(
    target_url: str,
    *,
    range_header: Optional[str] = None,
    user_agent: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
    started: Optional[float] = None,
) -> Response:
    """Stream `target_url` through this host.

    Always returns a `Response`, and its `status_code` mirrors the upstream one for
    error cases (403/404/410/...) so callers can react — `main.py` uses that to detect a
    revoked URL and re-extract. Connect failures become 502.

    `client` is injectable so tests can supply an `httpx.MockTransport` client.
    """
    started = time.monotonic() if started is None else started
    http = client or get_client()
    req_headers = _upstream_headers(range_header, user_agent)

    connect_started = time.monotonic()
    try:
        upstream_req = http.build_request("GET", target_url, headers=req_headers)
        upstream = await http.send(upstream_req, stream=True)
    except Exception as e:
        metrics.record_upstream_connect(time.monotonic() - connect_started)
        metrics.record_stream_error("connect")
        logger.error(f"[STREAM_PROXY] Upstream connection error: {e}")
        return JSONResponse(
            status_code=502,
            content={"error": "Bad Gateway", "message": f"Failed to connect to stream source: {e}"},
        )
    metrics.record_upstream_connect(time.monotonic() - connect_started)

    if upstream.status_code >= 400:
        status = upstream.status_code
        metrics.record_stream_error(status)
        logger.error(f"[STREAM_PROXY] upstream {status} (expired or IP-locked URL)")
        await _release(upstream)
        return JSONResponse(
            status_code=status,
            content={"error": f"Upstream returned HTTP {status}"},
        )

    resp_headers = {
        h: upstream.headers[h] for h in _PASS_THROUGH if upstream.headers.get(h) is not None
    }
    resp_headers.setdefault("accept-ranges", "bytes")

    released = False

    async def release_once() -> None:
        # Idempotent: called from the generator's `finally` on the normal path and from
        # the response's background task if the body is never iterated (client hangs up
        # between headers and first chunk). Without the second path that connection
        # would sit in the pool until GC finalized the generator.
        nonlocal released
        if released:
            return
        released = True
        await _release(upstream)

    async def body() -> AsyncIterator[bytes]:
        metrics.stream_started()
        first = True
        try:
            # aiter_raw, not aiter_bytes: bytes must match the `content-length` /
            # `content-range` we forwarded above.
            async for chunk in upstream.aiter_raw(_CHUNK):
                if first:
                    metrics.record_stream_ttfb(time.monotonic() - started)
                    first = False
                metrics.record_stream_bytes(len(chunk))
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as err:
            metrics.record_stream_error("transfer")
            logger.debug(f"[STREAM_PROXY] Stream disconnected: {err}")
        finally:
            metrics.stream_finished()
            await release_once()

    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        headers=resp_headers,
        background=BackgroundTask(release_once),
    )


async def _release(upstream: httpx.Response) -> None:
    try:
        await upstream.aclose()
    except Exception:
        pass

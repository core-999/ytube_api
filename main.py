from fastapi import FastAPI, Query, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
import time
import asyncio
import logging
import datetime
import hashlib
import base64
import threading
from typing import Optional
import httpx
import uvicorn
import inspect
from fastapi.routing import APIRoute
from fastapi.params import Depends as DependsParam
from pydantic.fields import FieldInfo
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from starlette.routing import Match
from starlette.responses import Response

from config import DAILY_LIMIT, ADMIN_LIMIT
from utils.url_validation import validate_youtube_target

# Import shared tools
from tools import (
    redis_client, generate_token, is_admin, get_user_token,
    set_user_token, revoke_user_token, get_user_by_token,
    get_user_request_count, set_user_request_count, increment_user_requests,
    increment_failed_requests
)

import os as _os


# ─────────────────────────── FastAPI ───────────────────────────

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bootstrap yt-dlp cookies on API startup so it works under `uvicorn main:app`
    # (any worker/replica), not just `python3 main.py`.
    # ponytail: with --workers>1 in ONE container the workers race on cookies.txt;
    # recommended scaling is WEB_CONCURRENCY=1 + multiple replicas (each writes its
    # own container-local file). Bump to a file lock only if you must run N>1 in one box.
    if not _os.getenv("TESTING"):
        try:
            from utils.logging_config import setup_json_logging
            setup_json_logging()
            from utils.cookies import bootstrap as bootstrap_cookies, start_refresh
            bootstrap_cookies()
            start_refresh()
        except Exception as e:
            logging.error(f"[STARTUP] Cookie bootstrap failed: {e}")
    yield
    # Release the Innertube fast-path connection pool on shutdown.
    try:
        from utils.innertube import close_client as close_innertube
        await close_innertube()
    except Exception:
        pass


app = FastAPI(
    title="yt-dlp_api API",
    description="API for yt-dlp-based search, streaming, and playlist extraction with Telegram bot integration",
    lifespan=lifespan,
)

# Rate limiting
FREE_PATHS = frozenset([
    "/", "/search", "/trending", "/suggest", "/health",
    "/rate-limit-status", "/docs", "/openapi.json", "/metrics",
    "/favicon.ico", "/favicon.svg",
])

_FREE_PREFIXES = (
    "/stream/resolver/",
    "/stream/proxy/",
)

# ─────────────────────────── Redirect Stream Storage ───────────────────────────
# Job state lives in Redis (key stream_job:{id} -> JSON {url, mode, extracted_url,
# extracted_time}) so /stream/redirect and /stream/resolver can land on different
# replicas behind a non-sticky load balancer. TTL covers the 45s resolver wait + buffer.
import json as _json
from tools import get_async_redis

_STREAM_TTL = 14400  # 4 hours (matches YouTube stream URL lifetime)


async def _job_get(stream_id: str) -> Optional[dict]:
    redis = await get_async_redis()
    raw = await redis.get(f"stream_job:{stream_id}")
    return _json.loads(raw) if raw else None


def _encode_stream_id(url: str, mode: str) -> str:
    """Generate a stable stream ID from URL + mode"""
    key = f"{mode}:{url}"
    return base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()).decode().rstrip('=')

def _start_background_extraction(stream_id: str, url: str, mode: str):
    """Start background task to extract streaming URL"""
    async def extract():
        try:
            if mode == "video":
                from utils.cache_manager import get_video_stream
                stream_url = await get_video_stream(url)
            else:
                from utils.cache_manager import get_stream
                stream_url = await get_stream(url)

            if stream_url:
                redis = await get_async_redis()
                job = await _job_get(stream_id)
                if job is not None:  # tolerate TTL expiry under load
                    job["extracted_url"] = stream_url
                    job["extracted_time"] = time.time()
                    await redis.set(f"stream_job:{stream_id}", _json.dumps(job), ex=_STREAM_TTL)
                    logging.info(f"[STREAM_RESOLVER] Extracted {mode} URL for {stream_id}")
        except Exception as e:
            logging.error(f"[STREAM_RESOLVER] Failed to extract {mode}: {e}")

    asyncio.create_task(extract())


def _resolve_mode(mode: str) -> str:
    return "video" if str(mode).lower() in ("video", "stream", "muxed") else "audio"


async def _ensure_stream_job(url: str, mode: str) -> str:
    validate_youtube_target(url)  # SSRF guard: only YouTube targets reach yt-dlp
    resolved_mode = _resolve_mode(mode)
    stream_id = _encode_stream_id(url, resolved_mode)

    redis = await get_async_redis()
    # SET NX: only the first replica to claim this id starts extraction; others reuse it.
    created = await redis.set(
        f"stream_job:{stream_id}",
        _json.dumps({"url": url, "mode": resolved_mode, "extracted_url": None, "extracted_time": None}),
        ex=_STREAM_TTL,
        nx=True,
    )
    if created:
        _start_background_extraction(stream_id, url, resolved_mode)
    else:
        # A long _STREAM_TTL means a job whose extraction failed would otherwise stay
        # dead for hours (the old 120s TTL hid this by expiring). Retry it — repeat
        # resolves are cheap, cache_manager serves them from cache.
        job = await _job_get(stream_id)
        if job is not None and job["extracted_url"] is None:
            _start_background_extraction(stream_id, url, resolved_mode)

    return stream_id


async def _await_extracted(stream_id: str) -> Optional[dict]:
    """Job with extracted_url populated (polling up to 45s), or None if it's gone.

    Shared by the resolver (redirects to the URL) and the proxy (streams its bytes).
    """
    job = await _job_get(stream_id)
    if job is None:
        return None
    if job["extracted_url"] is None:
        for _ in range(45):  # 45s: background extraction usually lands in 1-2s
            await asyncio.sleep(1)
            job = await _job_get(stream_id)
            if job is None or job["extracted_url"] is not None:
                break
    return job


def _make_https_url(url_obj) -> str:
    if hasattr(url_obj, "replace") and not isinstance(url_obj, str):
        return str(url_obj.replace(scheme="https"))
    s = str(url_obj)
    if s.startswith("http://"):
        return "https://" + s[7:]
    return s


def _make_temp_proxy(request: Request, stream_id: str) -> str:
    return _make_https_url(request.url_for("stream_proxy_by_id", stream_id=stream_id))


async def _make_temp_redirect(request: Request, url: str, mode: str = "video") -> str:
    stream_id = await _ensure_stream_job(url, mode)
    return _make_temp_proxy(request, stream_id)


async def _resolve_stream_url_for_info(request: Request, url: str, redirect: bool = True) -> str:
    """Return direct proxied stream URL."""
    stream_id = await _ensure_stream_job(url, "video")
    return _make_temp_proxy(request, stream_id)


async def _proxy_stream_response(target_url: str, request: Request) -> Response:
    """Stream media chunks from target_url back to client with Range request support."""
    req_headers = {}
    range_header = request.headers.get("range")
    if range_header:
        req_headers["range"] = range_header

    user_agent = request.headers.get("user-agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    req_headers["user-agent"] = user_agent

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=15.0, read=None, write=30.0, pool=30.0),
        follow_redirects=True,
    )

    try:
        upstream_req = client.build_request("GET", target_url, headers=req_headers)
        upstream_resp = await client.send(upstream_req, stream=True)
    except Exception as e:
        await client.aclose()
        logging.error(f"[STREAM_PROXY] Upstream connection error: {e}")
        return JSONResponse(
            status_code=502,
            content={"error": "Bad Gateway", "message": f"Failed to connect to stream source: {str(e)}"}
        )

    if upstream_resp.status_code in (403, 404, 410):
        status = upstream_resp.status_code
        await upstream_resp.aclose()
        await client.aclose()
        return JSONResponse(
            status_code=status,
            content={"error": f"Upstream returned HTTP {status}"}
        )

    # Headers to forward back to client
    resp_headers = {}
    for h in ("content-type", "content-length", "content-range", "accept-ranges", "content-disposition", "cache-control"):
        val = upstream_resp.headers.get(h)
        if val is not None:
            resp_headers[h] = val

    if "accept-ranges" not in resp_headers:
        resp_headers["accept-ranges"] = "bytes"

    async def stream_generator():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=128 * 1024):
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as err:
            logging.debug(f"[STREAM_PROXY] Stream disconnected: {err}")
        finally:
            try:
                await upstream_resp.aclose()
            except Exception:
                pass
            try:
                await client.aclose()
            except Exception:
                pass

    return StreamingResponse(
        stream_generator(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
    )


def _token_from_request(request: Request) -> Optional[str]:
    """Prefer `Authorization: Bearer <token>`; fall back to the deprecated ?token= query param."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.query_params.get("token")


async def get_current_user(token: Optional[str] = Query(None)):
    """Get current user from token"""
    if not token:
        return None
    try:
        user_id = await get_user_by_token(token)
        return user_id
    except:
        return None


async def require_token(request: Request):
    """Require valid token (header or ?token=) for protected endpoints"""
    user_id = await get_current_user(_token_from_request(request))
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Token required",
                "message": "Get your token from the Telegram bot via /start and send it as 'Authorization: Bearer <token>' (or the deprecated ?token= query param)"
            }
        )
    return user_id



class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in FREE_PATHS or any(
            request.url.path.startswith(prefix) for prefix in _FREE_PREFIXES
        ):
            return await call_next(request)

        token   = _token_from_request(request)
        user_id = await get_current_user(token)

        if not user_id:
            required_args, optional_args = get_arguments_for_request(request)
            return JSONResponse(
                status_code=401,
                content=jsonable_encoder({
                    "error":   "Token required",
                    "message": "Get your token from @ytdlp_nub_bot using /start",
                    "required_arguments": required_args,
                    "optional_arguments": optional_args,
                }),
            )

        user_limit = ADMIN_LIMIT if is_admin(user_id) else DAILY_LIMIT

        # --- single Redis round-trip: check + increment atomically ---
        # We increment optimistically; if over limit we return 429.
        # This avoids a separate GET before the INCR.
        new_count = await increment_user_requests(user_id)

        if new_count > user_limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error":              "Daily limit exceeded",
                    "message":            f"Limit: {user_limit} req/day. Search is always free.",
                    "remaining_requests": 0,
                    "reset_time":         "Resets at midnight UTC",
                },
            )

        response = await call_next(request)

        # Log failed requests (4xx / 5xx) with the error message
        if response.status_code >= 400:
            try:
                # Read the streaming body so we can inspect it
                body_chunks = []
                async for chunk in response.body_iterator:
                    body_chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
                body_bytes = b"".join(body_chunks)

                # Try to extract the error message from JSON
                error_msg = ""
                try:
                    import json as _json
                    payload = _json.loads(body_bytes)
                    error_msg = payload.get("error", "") or payload.get("detail", "") or payload.get("message", "")
                    if isinstance(error_msg, dict):
                        error_msg = error_msg.get("error", "") or error_msg.get("message", "") or str(error_msg)
                except Exception:
                    error_msg = body_bytes[:300].decode(errors="replace")

                await increment_failed_requests(
                    user_id,
                    status_code=response.status_code,
                    path=request.url.path,
                    error_message=str(error_msg),
                )

                # Rebuild the response since we consumed the body iterator
                from starlette.responses import Response as StarletteResponse
                response = StarletteResponse(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
            except Exception:
                pass  # never block a response for logging

        remaining = max(0, user_limit - new_count)
        reset_ts  = int(
            datetime.datetime.combine(
                datetime.date.today() + datetime.timedelta(days=1),
                datetime.time.min,
            ).timestamp()
        )
        response.headers["X-RateLimit-Limit"]     = str(user_limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"]     = str(reset_ts)

        return response


def clean_type_name(annotation) -> str:
    if annotation == inspect.Parameter.empty:
        return "any"
    
    # Handle typing wrappers like Optional, Union, etc.
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        args = getattr(annotation, "__args__", [])
        non_none_args = [arg for arg in args if arg is not type(None)]
        if len(non_none_args) == 1:
            return clean_type_name(non_none_args[0])
        elif len(non_none_args) > 1:
            return " | ".join(clean_type_name(arg) for arg in non_none_args)
            
    name = getattr(annotation, "__name__", str(annotation))
    if name == "str":
        return "string"
    if name == "int":
        return "integer"
    if name == "bool":
        return "boolean"
    if name == "float":
        return "number"
    return name


def get_endpoint_args(route: APIRoute):
    required_args = {}
    optional_args = {}
    
    sig = inspect.signature(route.endpoint)
    for name, param in sig.parameters.items():
        # Skip internal parameter types like Request or Response
        if param.annotation in (Request, Response) or name in ("request", "response"):
            continue
        # Skip dependencies
        if isinstance(param.default, DependsParam):
            continue
            
        param_type = clean_type_name(param.annotation)
        description = ""
        param_in = "query"
        
        # Check if it's a path parameter
        if f"{{{name}}}" in route.path:
            param_in = "path"
            
        if isinstance(param.default, FieldInfo):
            is_req = param.default.is_required()
            default_val = param.default.default
            # Handle PydanticUndefined default value
            if default_val == ... or default_val.__class__.__name__ == "PydanticUndefined":
                default_val = None
            description = param.default.description or ""
            
            # Determine location from FieldInfo type
            from fastapi.params import Query, Path, Header, Cookie, Body
            if isinstance(param.default, Path):
                param_in = "path"
            elif isinstance(param.default, Query):
                param_in = "query"
            elif isinstance(param.default, Header):
                param_in = "header"
            elif isinstance(param.default, Cookie):
                param_in = "cookie"
            elif isinstance(param.default, Body):
                param_in = "body"
        else:
            is_req = (param.default == inspect.Parameter.empty)
            default_val = None if is_req else param.default

        info = {
            "type": param_type,
            "in": param_in,
        }
        if description:
            info["description"] = description
            
        if is_req:
            required_args[name] = info
        else:
            info["default"] = default_val
            optional_args[name] = info
            
    return required_args, optional_args


def get_arguments_for_request(request: Request):
    required_args = {}
    optional_args = {}
    
    route = request.scope.get("route")
    if not route:
        for r in request.app.routes:
            match, _ = r.matches(request.scope)
            if match == Match.FULL:
                route = r
                break
                
    if route and isinstance(route, APIRoute):
        required_args, optional_args = get_endpoint_args(route)
        
    return required_args, optional_args


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    required_args, optional_args = get_arguments_for_request(request)
    
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({
            "error": "Validation Error",
            "message": "The endpoint was used incorrectly. Please verify the arguments below.",
            "details": exc.errors(),
            "endpoint": request.url.path,
            "required_arguments": required_args,
            "optional_arguments": optional_args
        })
    )


app.add_middleware(RateLimitMiddleware)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    from utils import metrics
    start = time.time()
    response = await call_next(request)
    # Use the route template (not the raw path) so per-id URLs don't explode cardinality
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    metrics.record(request.method, path, response.status_code, time.time() - start)
    return response


_ASSET_DIR = _os.path.dirname(__file__)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    return FileResponse(_os.path.join(_ASSET_DIR, "favicon.ico"), media_type="image/x-icon")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg():
    return FileResponse(_os.path.join(_ASSET_DIR, "ytdlpapi-icon.svg"), media_type="image/svg+xml")


@app.get("/metrics")
async def metrics_endpoint():
    from utils import metrics
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")


# ─────────────────────────── Endpoints ───────────────────────────

@app.get("/")
async def read_root():
    """API welcome page"""
    return {
        "name": "yt-dlp_api API",
        "version": "2026.3.12",
        "endpoints": {
            "/search": "Search songs via scrape or YouTube Data API (FREE)",
            "/trending": "Get trending music (FREE)",
            "/suggest": "Get song suggestions for a query (FREE)",
            "/stream": "Get stream URL (token required)",
            "/stream/redirect": "Get instant redirect URL for pytgcall (token required)",
            "/info": "Search + stream URL in one call (token required)",
            "/playlist": "Get all songs from a YouTube playlist (token required)",
            "/health": "Health check (FREE)",
            "/rate-limit-status": "Check your rate limit usage",
        },
        "free_endpoints": ["/search", "/trending", "/suggest", "/health"],
        "auth": "Get your token from the Telegram bot @ytdlp_nub_bot using /start",
        "redirect_note": "Use /stream/redirect with pytgcall for instant response + background extraction"
    }


@app.get("/search")
async def search_songs(
    q: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Number of results", ge=1, le=20),
    method: str = Query("scrape", description="Search method: 'scrape' (free) or 'api' (uses YouTube Data API)")
):
    """Search YouTube for songs — FREE (no token required)"""
    start_time = time.time()

    try:
        if method == "api":
            from utils.youtube_api import fetch_results
            results = await fetch_results(q, limit=limit)
            elapsed = round(time.time() - start_time, 2)
            return JSONResponse(content={
                "query": q,
                "method": "youtube_data_api",
                "results": results,
                "total_results": len(results),
                "time_taken": f"{elapsed} sec"
            })
        else:
            from utils.search_service import fetch_results
            data = await fetch_results(q, limit=limit)
            elapsed = round(time.time() - start_time, 2)
            return JSONResponse(content={
                "query": q,
                "method": "scrape",
                "results": data.get("main_results", []),
                "suggested": data.get("suggested", []),
                "total_results": len(data.get("main_results", [])),
                "time_taken": f"{elapsed} sec"
            })

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        return JSONResponse(
            content={"error": str(e), "time_taken": f"{elapsed} sec"},
            status_code=400
        )


@app.get("/stream/redirect")
async def stream_redirect(
    request: Request,
    q: str = Query(..., description="YouTube video URL"),
    mode: str = Query("video", description="Stream mode: 'video' or 'audio'"),
    token: str = Query(..., description="Your API token"),
    user_id: int = Depends(require_token)
):
    """Get instant redirect URL for streaming (pytgcall friendly!)."""
    resolved_mode = _resolve_mode(mode)
    stream_id = await _ensure_stream_job(q, resolved_mode)

    # Return 307 Temporary Redirect to resolver/proxy
    return RedirectResponse(
        url=_make_temp_proxy(request, stream_id),
        status_code=307,
    )


@app.get("/stream/resolver/{stream_id}")
@app.get("/stream/proxy/{stream_id}")
async def stream_resolver(request: Request, stream_id: str):
    """Resolver endpoint for proxied streaming."""
    job = await _await_extracted(stream_id)
    if job is None:
        return JSONResponse(
            content={"error": "Stream not found", "hint": "Use /stream or /stream/redirect to get a valid URL"},
            status_code=404
        )

    if not job.get("extracted_url"):
        return JSONResponse(
            content={"error": "Failed to extract stream URL", "url": job.get("url")},
            status_code=500
        )

    resp = await _proxy_stream_response(job["extracted_url"], request)
    if resp.status_code == 403 and job.get("url") and job.get("mode"):
        logging.info(f"[STREAM_PROXY] Got 403 from upstream for {stream_id}, refreshing stream URL...")
        _start_background_extraction(stream_id, job["url"], job["mode"])
        refreshed_job = await _await_extracted(stream_id)
        if refreshed_job and refreshed_job.get("extracted_url") and refreshed_job["extracted_url"] != job["extracted_url"]:
            resp = await _proxy_stream_response(refreshed_job["extracted_url"], request)

    return resp


@app.get("/stream")
async def get_stream_url(
    request: Request,
    q: str = Query(..., description="YouTube video URL"),
    redirect: bool = Query(False, description="Return a temporary redirect URL instead of the final stream URL"),
    mode: str = Query("video", description="Stream mode: 'video' or 'audio'"),
    token: Optional[str] = Query(None, description="API token (deprecated — prefer 'Authorization: Bearer <token>')"),
    user_id: int = Depends(require_token)
):
    """Get proxified stream URL for a YouTube video."""
    validate_youtube_target(q)  # SSRF guard
    start_time = time.time()

    try:
        resolved_mode = _resolve_mode(mode)
        stream_id = await _ensure_stream_job(q, resolved_mode)
        stream_url = _make_temp_proxy(request, stream_id)
        elapsed = round(time.time() - start_time, 2)

        if redirect:
            return JSONResponse(content={
                "url": q,
                "redirect_url": stream_url,
                "stream_url": None,
                "time_taken": f"{elapsed} sec"
            })

        return JSONResponse(content={
            "url": q,
            "stream_url": stream_url,
            "time_taken": f"{elapsed} sec"
        })

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        return JSONResponse(
            content={"error": str(e), "time_taken": f"{elapsed} sec"},
            status_code=400
        )


@app.get("/info")
async def video_info(
    request: Request,
    q: str = Query(..., description="YouTube video URL or search query"),
    max_results: int = Query(1, description="Max results for search queries", ge=1, le=10),
    redirect: bool = Query(True, description="Return a temporary redirect URL instead of waiting for the final stream"),
    token: Optional[str] = Query(None, description="API token (deprecated — prefer 'Authorization: Bearer <token>')"),
    user_id: int = Depends(require_token)
):
    """Get video info + stream URL (token required)"""
    validate_youtube_target(q)  # SSRF guard (bare search phrases pass — no host to SSRF)
    start_time = time.time()

    def extract_video_id_from_url(value: str) -> str | None:
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(value)
        if "youtu.be" in parsed.netloc:
            candidate = parsed.path.strip("/")
            return candidate or None

        if "youtube.com" in parsed.netloc:
            query_id = parse_qs(parsed.query).get("v", [None])[0]
            if query_id:
                return query_id

        return None

    try:
        # Check if it's a YouTube URL
        import re
        yt_url_pattern = re.compile(r'(youtube\.com|youtu\.be)')
        is_url = bool(yt_url_pattern.search(q))

        if is_url:
            # Direct URL — get stream and info concurrently
            from utils.youtube_api import GetVideoById

            video_id = extract_video_id_from_url(q)
            metadata_task = asyncio.create_task(GetVideoById(video_id)) if video_id else None

            stream_url = await _resolve_stream_url_for_info(request, q, redirect)
            metadata_result = await metadata_task if metadata_task else None
            info = metadata_result if isinstance(metadata_result, dict) else {}

            elapsed = round(time.time() - start_time, 2)
            return JSONResponse(content={
                "query_type": "url",
                "title": info.get("title"),
                "duration": info.get("duration"),
                "youtube_link": q,
                "channel_name": info.get("channel_name") or info.get("channel") or info.get("artist_name"),
                "views": info.get("views"),
                "video_id": info.get("video_id"),
                "stream_url": stream_url,
                "thumbnail": info.get("thumbnail"),
                "time_taken": f"{elapsed} sec"
            })
        else:
            # Search query
            from utils.search_service import fetch_results
            search_data = await fetch_results(q, limit=max_results)

            if max_results == 1 and search_data.get("main_results"):
                # Single result — also get stream URL
                result = search_data["main_results"][0]
                video_url = result.get("url", "")

                stream_url = await _resolve_stream_url_for_info(request, video_url, redirect)
                elapsed = round(time.time() - start_time, 2)
                return JSONResponse(content={
                    "query_type": "search",
                    "query": q,
                    "title": result.get("title"),
                    "duration": result.get("duration"),
                    "youtube_link": result.get("url"),
                    "channel_name": result.get("channel"),
                    "views": result.get("views"),
                    "video_id": result.get("video_id"),
                    "stream_url": stream_url,
                    "thumbnail": result.get("thumbnail"),
                    "time_taken": f"{elapsed} sec"
                })
            else:
                # Multiple results — return list only
                elapsed = round(time.time() - start_time, 2)
                results = search_data.get("main_results", [])
                return JSONResponse(content={
                    "query_type": "search",
                    "query": q,
                    "results": results,
                    "total_results": len(results),
                    "time_taken": f"{elapsed} sec"
                })

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        return JSONResponse(
            content={"error": str(e), "time_taken": f"{elapsed} sec"},
            status_code=400
        )


@app.get("/trending")
async def trending_songs(
    limit: int = Query(10, description="Number of trending songs", ge=1, le=20)
):
    """Get trending songs — FREE (no token required)"""
    start_time = time.time()

    try:
        from utils.search_service import fetch_trending
        results = await fetch_trending(limit=limit)
        elapsed = round(time.time() - start_time, 2)

        return JSONResponse(content={
            "results": results,
            "total_results": len(results),
            "time_taken": f"{elapsed} sec"
        })

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        return JSONResponse(
            content={"error": str(e), "time_taken": f"{elapsed} sec"},
            status_code=400
        )


@app.get("/suggest")
async def suggest_songs(
    q: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Number of suggestions", ge=1, le=20)
):
    """Get song suggestions — FREE (no token required)"""
    start_time = time.time()

    try:
        from utils.search_service import fetch_suggestions
        results = await fetch_suggestions(q, limit=limit)
        elapsed = round(time.time() - start_time, 2)

        return JSONResponse(content={
            "query": q,
            "results": results,
            "total_results": len(results),
            "time_taken": f"{elapsed} sec"
        })

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        return JSONResponse(
            content={"error": str(e), "time_taken": f"{elapsed} sec"},
            status_code=400
        )


@app.get("/playlist")
async def playlist_songs(
    url: str = Query(..., description="YouTube playlist URL or playlist ID (e.g. PLxxxxxxx, RDxxxxxx)"),
    token: Optional[str] = Query(None, description="API token (deprecated — prefer 'Authorization: Bearer <token>')"),
    user_id: int = Depends(require_token)
):
    """Get all songs from a YouTube playlist.

    Supports normal playlists (PL...), auto-generated playlists (OL..., UU...),
    and YouTube Mix playlists (RD...).
    """
    start_time = time.time()

    try:
        from utils.playlist_parser import extract_playlist
        songs = await extract_playlist(url)
        elapsed = round(time.time() - start_time, 2)

        return JSONResponse(content={
            "playlist_url": url,
            "songs": songs,
            "total_songs": len(songs),
            "time_taken": f"{elapsed} sec"
        })

    except ValueError as e:
        elapsed = round(time.time() - start_time, 2)
        return JSONResponse(
            content={"error": str(e), "time_taken": f"{elapsed} sec"},
            status_code=400
        )
    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        return JSONResponse(
            content={"error": str(e), "time_taken": f"{elapsed} sec"},
            status_code=500
        )


# `/version` endpoint removed — startup info helper removed from source-only repo


@app.get("/health")
async def health_check():
    """Quick health check endpoint"""
    return {"status": "ok"}


@app.get("/rate-limit-status")
async def rate_limit_status(token: Optional[str] = Query(None, description="Your API token")):
    """Check current rate limit status"""
    user_id = await get_current_user(token)
    if user_id:
        used = await get_user_request_count(user_id)
        limit = ADMIN_LIMIT if is_admin(user_id) else DAILY_LIMIT

        return {
            "user_id": user_id,
            "daily_limit": limit,
            "requests_used": used,
            "requests_remaining": max(0, limit - used),
            "reset_time": "Resets at midnight UTC",
            "is_admin": is_admin(user_id),
            "auth_method": "token"
        }
    else:
        return {
            "error": "No token provided",
            "message": "Please get your token from the Telegram bot using /start command and add it as ?token=YOUR_TOKEN",
            "auth_method": "none"
        }


# ─────────────────────────── Run Services ───────────────────────────

def start_services():
    print("🌐 Starting FastAPI server on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info", loop="asyncio")


if __name__ == "__main__":
    try:
        from config import BOT_TOKEN, START_BOT
        if BOT_TOKEN and START_BOT:
            try:
                from bot import run_bot
                threading.Thread(target=start_services, daemon=True).start()
                run_bot()
            except Exception as e:
                print(f"Bot failed: {e}, running FastAPI API standalone...")
                start_services()
        else:
            if not START_BOT:
                print("ℹ️ Telegram bot disabled via configuration (START_BOT=false).")
            start_services()
    except KeyboardInterrupt:
        print("Services stopped by user")
    except Exception as e:
        print(f"Error starting services: {e}")

from fastapi import FastAPI, Query, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
import time
import asyncio
import logging
import datetime
import hashlib
import base64
from typing import Optional
from collections import defaultdict
import uvicorn
import threading
from pyrogram import Client, idle

# Telegram Bot Configuration
API_ID = 21856699
API_HASH = '73f10cf0979637857170f03d4c86f251'
BOT_TOKEN = '8246299769:AAF2jRzQBJmkOqL_146jKG0EjWbeTSC78eU'
GROUP = "nub_coder_s"
CHANNEL = "nub_coders"

# Import shared tools
from tools import (
    redis_client, generate_token, is_admin, get_user_token,
    set_user_token, revoke_user_token, get_user_by_token,
    get_user_request_count, set_user_request_count, increment_user_requests,
    increment_failed_requests
)

# Initialize Pyrogram client with plugins
telegram_app = Client(
    "ytdlp_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN, in_memory=True,
    plugins=dict(root="plugins"),
    device_model="Desktop",
    system_version="Windows 10",
    app_version="3.4.3 x64",
    lang_code="en",
    lang_pack="tdesktop"
)

def setup_bot_commands():
    """Set up bot commands menu"""
    from pyrogram.types import BotCommand

    commands = [
        BotCommand("start", "🚀 Get your API token and welcome message"),
        BotCommand("menu", "📋 Show main menu with options"),
        BotCommand("ping", "🏓 Check bot latency"),
        BotCommand("status", "📊 Check your usage statistics"),
        BotCommand("token", "🔑 View your current API token"),
        BotCommand("revoke", "🔄 Revoke your current token"),
        BotCommand("help", "❓ Get help and API documentation"),
    ]

    try:
        telegram_app.set_bot_commands(commands)
        print("✅ Bot commands set successfully")
    except Exception as e:
        print(f"⚠️ Failed to set bot commands: {e}")

try:
    telegram_app.start()
    setup_bot_commands()
    telegram_app.stop()
except Exception as e:
    print(f"Bot setup skipped (will retry at runtime): {e}")


# ─────────────────────────── FastAPI ───────────────────────────

app = FastAPI(
    title="yt-dlp_api API",
    description="API for yt-dlp-based search, streaming, and playlist extraction with Telegram bot integration"
)

# Rate limiting
daily_request_counts = defaultdict(lambda: {"count": 0, "date": datetime.date.today()})
DAILY_LIMIT = 1000
ADMIN_LIMIT = 10000

FREE_PATHS = frozenset([
    "/", "/search", "/trending", "/suggest", "/health",
    "/rate-limit-status", "/docs", "/openapi.json",
])

_FREE_PREFIXES = (
    "/stream/resolver/",
    "/video-stream/resolver/",
)

# ─────────────────────────── Redirect Stream Storage ───────────────────────────
# Maps stream_id -> {url, mode, extracted_url, extracted_time}
_STREAM_CACHE = {}  # In-memory cache for redirect stream URLs

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
                _STREAM_CACHE[stream_id]["extracted_url"] = stream_url
                _STREAM_CACHE[stream_id]["extracted_time"] = time.time()
                logging.info(f"[STREAM_RESOLVER] Extracted {mode} URL for {stream_id}")
        except Exception as e:
            logging.error(f"[STREAM_RESOLVER] Failed to extract {mode}: {e}")
    
    asyncio.create_task(extract())


def _resolve_mode(mode: str) -> str:
    return "video" if mode == "video" else "audio"


def _ensure_stream_job(url: str, mode: str) -> str:
    resolved_mode = _resolve_mode(mode)
    stream_id = _encode_stream_id(url, resolved_mode)

    if stream_id not in _STREAM_CACHE:
        _STREAM_CACHE[stream_id] = {
            "url": url,
            "mode": resolved_mode,
            "extracted_url": None,
            "extracted_time": None,
        }
        _start_background_extraction(stream_id, url, resolved_mode)

    return stream_id


def _make_temp_redirect(request: Request, url: str, mode: str) -> str:
    stream_id = _ensure_stream_job(url, mode)
    return str(
        request.url_for("stream_resolver", stream_id=stream_id)
        .replace(scheme="https")
    )


async def get_current_user(token: Optional[str] = Query(None)):
    """Get current user from token"""
    if not token:
        return None
    try:
        user_id = get_user_by_token(token)
        return user_id
    except:
        return None


async def require_token(token: Optional[str] = Query(None, description="Your API token")):
    """Require valid token for protected endpoints"""
    user_id = await get_current_user(token)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Token required",
                "message": "Please get your token from the Telegram bot using /start command and add it as ?token=YOUR_TOKEN"
            }
        )
    return user_id



class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in FREE_PATHS or any(
            request.url.path.startswith(prefix) for prefix in _FREE_PREFIXES
        ):
            return await call_next(request)

        token   = request.query_params.get("token")
        user_id = await get_current_user(token)

        if not user_id:
            return JSONResponse(
                status_code=401,
                content={
                    "error":   "Token required",
                    "message": "Get your token from @ytdlp_nub_bot using /start",
                },
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


app.add_middleware(RateLimitMiddleware)


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
            "/stream": "Get audio or video stream URL (token required)",
            "/stream/redirect": "Get instant redirect URL for pytgcall (token required)",
                "/video-stream": "Get separate video + audio URLs (token required)",
            "/video-stream/redirect": "Get instant redirect URL for video/audio (token required)",
            "/info": "Search + stream URL in one call (token required)",
            "/playlist": "Get all songs from a YouTube playlist (token required)",
            "/health": "Health check (FREE)",
            "/rate-limit-status": "Check your rate limit usage",
        },
        "free_endpoints": ["/search", "/trending", "/suggest", "/health"],
        "auth": "Get your token from the Telegram bot @ytdlp_nub_bot using /start",
        "redirect_note": "Use /stream/redirect and /video-stream/redirect with pytgcall for instant response + background extraction"
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


@app.get("/video-stream/redirect")
async def video_stream_redirect(
    request: Request,
    q: str = Query(..., description="YouTube video URL"),
    type: str = Query("audio", description="Which stream: 'video' (mp4) or 'audio' (m4a)"),
    token: str = Query(..., description="Your API token"),
    user_id: int = Depends(require_token)
):
    """Get instant redirect URL for video or audio stream (pytgcall friendly!)."""
    stream_id = _ensure_stream_job(q, "video" if type == "video" else "audio")

    # Return 307 Temporary Redirect to resolver
    return RedirectResponse(
        url=str(
            request.url_for("video_stream_resolver", stream_id=stream_id)
            .include_query_params(token=token)
            .replace(scheme="https")
        ),
        status_code=307,
    )


@app.get("/video-stream/resolver/{stream_id}")
async def video_stream_resolver(stream_id: str):
    """Resolver endpoint for video stream redirect."""
    if stream_id not in _STREAM_CACHE:
        return JSONResponse(
            content={"error": "Stream not found", "hint": "Use /video-stream/redirect to get a valid URL"},
            status_code=404
        )
    
    cache_entry = _STREAM_CACHE[stream_id]
    
    # If not extracted yet, wait up to 45s for extraction
    if cache_entry["extracted_url"] is None:
        logging.info(f"[VIDEO_STREAM_RESOLVER] Waiting for extraction... {stream_id}")
        for i in range(45):  # 45 second timeout
            if cache_entry["extracted_url"] is not None:
                break
            await asyncio.sleep(1)
    
    if cache_entry["extracted_url"]:
        logging.info(f"[VIDEO_STREAM_RESOLVER] Redirecting to stream URL {stream_id}")
        return RedirectResponse(
            url=cache_entry["extracted_url"],
            status_code=307
        )
    else:
        return JSONResponse(
            content={"error": "Failed to extract stream URL", "url": cache_entry["url"]},
            status_code=500
        )


@app.get("/stream/redirect")
async def stream_redirect(
    request: Request,
    q: str = Query(..., description="YouTube video URL"),
    mode: str = Query("audio", description="Mode: 'audio' or 'video'"),
    token: str = Query(..., description="Your API token"),
    user_id: int = Depends(require_token)
):
    """Get instant redirect URL for streaming (pytgcall friendly!)."""
    stream_id = _ensure_stream_job(q, mode)

    # Return 307 Temporary Redirect to resolver
    return RedirectResponse(
        url=str(
            request.url_for("stream_resolver", stream_id=stream_id)
            .include_query_params(token=token)
            .replace(scheme="https")
        ),
        status_code=307,
    )


@app.get("/stream/resolver/{stream_id}")
async def stream_resolver(stream_id: str):
    """Resolver endpoint for redirect streaming."""
    if stream_id not in _STREAM_CACHE:
        return JSONResponse(
            content={"error": "Stream not found", "hint": "Use /stream/redirect to get a valid URL"},
            status_code=404
        )
    
    cache_entry = _STREAM_CACHE[stream_id]
    
    # If not extracted yet, wait up to 45s for extraction
    if cache_entry["extracted_url"] is None:
        logging.info(f"[STREAM_RESOLVER] Waiting for extraction... {stream_id}")
        for i in range(45):  # 45 second timeout
            if cache_entry["extracted_url"] is not None:
                break
            await asyncio.sleep(1)
    
    if cache_entry["extracted_url"]:
        logging.info(f"[STREAM_RESOLVER] Redirecting to stream URL {stream_id}")
        return RedirectResponse(
            url=cache_entry["extracted_url"],
            status_code=307
        )
    else:
        return JSONResponse(
            content={"error": "Failed to extract stream URL", "url": cache_entry["url"]},
            status_code=500
        )


@app.get("/stream")
async def get_stream_url(
    request: Request,
    q: str = Query(..., description="YouTube video URL"),
    mode: str = Query("audio", description="Mode: 'audio' or 'video'"),
    redirect: bool = Query(False, description="Return a temporary redirect URL instead of the final stream URL"),
    token: str = Query(..., description="Your API token"),
    user_id: int = Depends(require_token)
):
    """Get stream URL for a YouTube video.

    Modes:
    - `audio`: Best audio stream (m4a)
    - `video`: Best combined video+audio (mp4, 360p)
    """
    start_time = time.time()

    try:
        if redirect:
            elapsed = round(time.time() - start_time, 2)
            return JSONResponse(content={
                "url": q,
                "mode": mode,
                "redirect_url": _make_temp_redirect(request, q, mode),
                "stream_url": None,
                "time_taken": f"{elapsed} sec"
            })

        if mode == "video":
            from utils.cache_manager import get_video_stream
            stream_url = await get_video_stream(q)
        else:
            from utils.cache_manager import get_stream
            stream_url = await get_stream(q)

        elapsed = round(time.time() - start_time, 2)

        if stream_url:
            return JSONResponse(content={
                "url": q,
                "mode": mode,
                "stream_url": stream_url,
                "time_taken": f"{elapsed} sec"
            })
        else:
            return JSONResponse(
                content={"error": "Failed to extract stream URL", "time_taken": f"{elapsed} sec"},
                status_code=500
            )

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        return JSONResponse(
            content={"error": str(e), "time_taken": f"{elapsed} sec"},
            status_code=400
        )


@app.get("/video-stream")
async def video_stream_urls(
    request: Request,
    q: str = Query(..., description="YouTube video URL"),
    redirect: bool = Query(False, description="Return a temporary redirect URL instead of separate stream URLs"),
    token: str = Query(..., description="Your API token"),
    user_id: int = Depends(require_token)
):
    """Get separate best-quality video and audio URLs.

    Returns two URLs: bestvideo (mp4) + bestaudio (m4a).
    Use these with ffmpeg or a player that supports dual-source playback.
    """
    start_time = time.time()

    try:
        if redirect:
            elapsed = round(time.time() - start_time, 2)
            return JSONResponse(content={
                "url": q,
                "redirect_url": _make_temp_redirect(request, q, "video"),
                "stream_url": None,
                "time_taken": f"{elapsed} sec"
            })

        from utils.media_extractor import resolve_stream_urls
        video_url, audio_url = await resolve_stream_urls(q)
        elapsed = round(time.time() - start_time, 2)

        if video_url and audio_url:
            return JSONResponse(content={
                "url": q,
                "video_url": video_url,
                "audio_url": audio_url,
                "time_taken": f"{elapsed} sec"
            })
        else:
            return JSONResponse(
                content={"error": "Failed to extract video+audio URLs", "time_taken": f"{elapsed} sec"},
                status_code=500
            )

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
    mode: str = Query("audio", description="Mode: 'audio' for audio-only, 'video' for video stream"),
    redirect: bool = Query(True, description="Return a temporary redirect URL instead of waiting for the final stream"),
    token: str = Query(..., description="Your API token"),
    user_id: int = Depends(require_token)
):
    """Get video info + stream URL (token required)"""
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

            if redirect:
                temp_redirect_url = _make_temp_redirect(request, q, mode)
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
                    "stream_url": temp_redirect_url,
                    "thumbnail": info.get("thumbnail"),
                    "time_taken": f"{elapsed} sec"
                })

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
                "stream_url": _make_temp_redirect(request, q, mode),
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
                    "stream_url": _make_temp_redirect(request, video_url, mode),
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
    token: str = Query(..., description="Your API token"),
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
        import asyncio
        threading.Thread(target=start_services, daemon=True).start()
        try:
            telegram_app.start()
            me = telegram_app.me
            print(f"🤖 Bot Started: @{me.username} ({me.first_name}) [ID: {me.id}]")
            idle()
            telegram_app.stop()
        except Exception as e:
            print(f"Bot failed: {e}, API still running...")
            import time as _time
            while True:
                _time.sleep(3600)
    except KeyboardInterrupt:
        print("Services stopped by user")
    except Exception as e:
        print(f"Error starting services: {e}")

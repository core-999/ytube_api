import os
import hashlib
import json
import time
import logging
from urllib.parse import urlparse, parse_qs

from utils.innertube import resolve as innertube_resolve
from utils.ytdlp_runner import resolve_g

__all__ = ["get_stream", "get_video_stream", "invalidate"]

logger = logging.getLogger("ytube_api.Stream")

_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
os.makedirs(_CACHE_DIR, exist_ok=True)

_MEM_CACHE = {}
_REDIS_CLIENT = None  # Lazy initialized

async def _get_redis():
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        try:
            from tools import get_async_redis
            _REDIS_CLIENT = await get_async_redis()
        except Exception:
            _REDIS_CLIENT = False  # Disable if unavailable
    return _REDIS_CLIENT if _REDIS_CLIENT else None


def _key(url: str, prefix: str = "") -> str:
    return hashlib.md5((prefix + url).encode()).hexdigest()


def _cache_path(url: str, prefix: str = "") -> str:
    return os.path.join(_CACHE_DIR, _key(url, prefix) + ".json")


def _extract_expire(stream_url: str) -> int | None:
    try:
        q = parse_qs(urlparse(stream_url).query)
        expire = int(q.get("expire", [0])[0])
        return expire if expire > int(time.time()) else None
    except Exception:
        return None


def _read_cache(url: str, prefix: str = "") -> tuple[str | None, int]:
    """Read cache and return (url, remaining_ttl). TTL -1 means expired."""
    path = _cache_path(url, prefix)

    if not os.path.exists(path):
        return None, -1

    try:
        with open(path, "r") as f:
            data = json.load(f)

        expire = data.get("expire", 0)
        remaining = expire - time.time()

        if remaining > 15:  # Only return if 15s buffer remains
            logger.debug(f"[CACHE HIT] {prefix}{url[:80]}... (expires in {int(remaining)}s)")
            return data.get("url"), int(remaining)

        logger.debug(f"[CACHE EXPIRED] {prefix}{url[:80]}... removing")
        try:
            os.remove(path)
        except Exception:
            pass

    except Exception as e:
        logger.debug(f"[CACHE READ ERROR] {e}")
        try:
            os.remove(path)
        except Exception:
            pass

    return None, -1


def _write_cache(url: str, stream_url: str, prefix: str = ""):
    expire = _extract_expire(stream_url)
    if not expire:
        logger.warning(f"[CACHE SKIP] No expire found in stream URL for {url[:80]}")
        return

    try:
        with open(_cache_path(url, prefix), "w") as f:
            json.dump(
                {
                    "url": stream_url,
                    "expire": expire,
                },
                f,
            )
        logger.info(f"[CACHE WRITE] {prefix}{url[:80]}... (expires in {int(expire - time.time())}s)")
    except Exception as e:
        logger.error(f"[CACHE WRITE ERROR] {e}")


async def invalidate(url: str, prefix: str = "") -> None:
    """Forget a cached stream URL so the next resolve re-extracts.

    Needed because googlevideo can revoke a URL (403/410) long before the `expire`
    stamped into it, and both cache layers key off that stamp — so without this an
    already-dead URL keeps being served as a fresh cache hit until it "expires".
    Both layers must go: Redis is checked first, the file cache would repopulate it.
    """
    try:
        os.remove(_cache_path(url, prefix))
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"[CACHE INVALIDATE] file remove failed: {e}")

    redis = await _get_redis()
    if redis:
        try:
            await redis.delete(f"cache:{prefix}{url}")
        except Exception as e:
            logger.error(f"[CACHE INVALIDATE] redis delete failed: {e}")

    logger.info(f"[CACHE INVALIDATE] {prefix}{url[:80]}")


async def _run_yt_dlp(url: str, format_selector: str, cookies: str | None):
    """yt-dlp fallback — client/cookie policy lives in utils/ytdlp_runner.py."""
    return await resolve_g(url, format_selector, cookies, tag="YT-DLP")


async def _resolve(url: str, kind: str, format_selector: str, cookies: str | None):
    """Innertube fast path first (~0.15 s, anonymous), yt-dlp -g as fallback."""
    stream_url = await innertube_resolve(url, kind)
    if stream_url:
        logger.info(f"[INNERTUBE] ✅ {kind} {url[:80]}")
        return stream_url
    return await _run_yt_dlp(url, format_selector, cookies)


async def get_stream(url: str, cookies: str | None = None) -> str | None:
    prefix = "audio:"
    
    # 1. Read from Redis cache (if redis available)
    redis = await _get_redis()
    if redis:
        try:
            cached_url = await redis.get(f"cache:{prefix}{url}")
            if cached_url:
                logger.info(f"[REDIS CACHE HIT] {prefix}{url[:80]}...")
                return cached_url
        except Exception as e:
            logger.error(f"[REDIS GET ERROR] {e}")

    # 2. Read from local file cache
    cached_url, remaining_ttl = _read_cache(url, prefix)
    if cached_url:
        # Re-populate Redis if we missed it
        if redis:
            try:
                await redis.setex(f"cache:{prefix}{url}", remaining_ttl, cached_url)
            except Exception:
                pass
        return cached_url

    # 3. Resolve — Innertube first, yt-dlp fallback
    stream_url = await _resolve(url, "audio", "251/250/bestaudio[ext=m4a]/bestaudio", cookies)
    if stream_url:
        # 4. Write cache
        _write_cache(url, stream_url, prefix)
        expire = _extract_expire(stream_url)
        if expire and redis:
            ttl = int(expire - time.time())
            if ttl > 0:
                try:
                    await redis.setex(f"cache:{prefix}{url}", ttl, stream_url)
                except Exception:
                    pass
    return stream_url


async def get_video_stream(url: str, cookies: str | None = None) -> str | None:
    prefix = "video:"
    
    # 1. Read from Redis cache
    redis = await _get_redis()
    if redis:
        try:
            cached_url = await redis.get(f"cache:{prefix}{url}")
            if cached_url:
                logger.info(f"[REDIS CACHE HIT] {prefix}{url[:80]}...")
                return cached_url
        except Exception as e:
            logger.error(f"[REDIS GET ERROR] {e}")

    # 2. Read from local file cache
    cached_url, remaining_ttl = _read_cache(url, prefix)
    if cached_url:
        if redis:
            try:
                await redis.setex(f"cache:{prefix}{url}", remaining_ttl, cached_url)
            except Exception:
                pass
        return cached_url

    # 3. Resolve — Innertube first, yt-dlp fallback
    stream_url = await _resolve(url, "muxed", "22/18/best[ext=mp4]", cookies)
    if stream_url:
        # 4. Write cache
        _write_cache(url, stream_url, prefix)
        expire = _extract_expire(stream_url)
        if expire and redis:
            ttl = int(expire - time.time())
            if ttl > 0:
                try:
                    await redis.setex(f"cache:{prefix}{url}", ttl, stream_url)
                except Exception:
                    pass
    return stream_url


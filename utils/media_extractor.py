import asyncio
import logging
import time

from utils.innertube import resolve_both
from utils.ytdlp_runner import resolve_g

logger = logging.getLogger("yt_dlp_api.Video_Stream")

# The selectors the yt-dlp fallback uses. utils/innertube.py mirrors these itag
# for itag, so both paths return the same codecs.
_VIDEO_SELECTOR = "22/18/best[ext=mp4]"
_AUDIO_SELECTOR = "251/250/bestaudio[ext=m4a]/bestaudio"


async def _extract_video(url: str, cookies: str | None = None):
    """Extract video stream in parallel task"""
    return await resolve_g(url, _VIDEO_SELECTOR, cookies, tag="VIDEO_EXTRACT")


async def _extract_audio(url: str, cookies: str | None = None):
    """Extract audio stream in parallel task"""
    return await resolve_g(url, _AUDIO_SELECTOR, cookies, tag="AUDIO_EXTRACT")


async def resolve_stream_urls(url: str, cookies: str | None = None):
    """Resolve (video, audio) URLs — Innertube first, yt-dlp subprocesses as fallback."""
    start = time.time()

    # One Innertube player call carries both streams, so the happy path costs a
    # single HTTP request instead of two node-backed subprocesses.
    video_url, audio_url = await resolve_both(url)
    if video_url and audio_url:
        logger.info(f"[VIDEO_AUDIO] ✅ Innertube in {round(time.time() - start, 2)}s")
        return video_url, audio_url

    logger.info("[VIDEO_AUDIO] Innertube incomplete — falling back to yt-dlp (parallel)")
    # Only re-fetch what Innertube missed; a partial hit still saves a subprocess.
    video_task = asyncio.create_task(
        _extract_video(url, cookies) if not video_url else _done(video_url))
    audio_task = asyncio.create_task(
        _extract_audio(url, cookies) if not audio_url else _done(audio_url))
    video_url, audio_url = await asyncio.gather(video_task, audio_task)

    elapsed = round(time.time() - start, 2)
    if video_url and audio_url:
        logger.info(f"[VIDEO_AUDIO] ✅ Both extracted in {elapsed}s")
        return video_url, audio_url

    logger.error(f"[VIDEO_AUDIO] ❌ Failed after {elapsed}s — "
                 f"video: {video_url is not None}, audio: {audio_url is not None}")
    return None, None


async def _done(value: str) -> str:
    """Already-resolved value, shaped as a coroutine so gather() stays uniform."""
    return value

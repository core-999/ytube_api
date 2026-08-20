"""Innertube fast path — the primary stream resolver; yt-dlp is the fallback.

A direct POST to /youtubei/v1/player on the ANDROID client (androidSdkVersion=30)
returns plain, UNciphered googlevideo URLs, so there is no signature/n-param JS to
solve and no node runtime to spawn: ~0.15 s against ~1.6 s for a `yt-dlp -g`
subprocess. Fully anonymous — no cookie, proxy or PO token.

Deliberately NOT handled here, left to the yt-dlp fallback:
  * age-gated / members-only videos — need a logged-in session
  * ciphered or SABR-only responses — need a JS runtime
Anything this module cannot resolve returns None and the caller falls back, so a
YouTube-side change degrades to the old path instead of breaking the endpoint.

Format picks mirror the yt-dlp selectors they replace, itag for itag, so the API
keeps returning the same codecs it always did (opus audio, mp4 muxed video).
"""
import logging
import re

import httpx
import orjson

logger = logging.getLogger("ytube_api.innertube")

# Public, non-secret Innertube key (shipped in youtube.com's own JS).
_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
_URL = f"https://youtubei.googleapis.com/youtubei/v1/player?key={_KEY}"

_ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/v/|/live/)([A-Za-z0-9_-]{11})")
_BARE_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")

# One shared client for the lifetime of the process (matches search_service).
_client = httpx.AsyncClient(http2=True, timeout=8)

_ANDROID_UA = "com.google.android.youtube/20.10.38 (Linux; U; Android 11) gzip"


def _ladder(vid: str, visitor: str | None) -> tuple:
    """Client ladder: ANDROID first (widest unciphered format set), then two
    clients that recover videos ANDROID alone refuses. clientVersion strings
    mirror yt-dlp's INNERTUBE_CLIENTS — a stale one is the #1 silent breaker,
    so refresh them from yt-dlp if extraction starts failing across the board.
    """
    return (
        ("android_vr", {
            "clientName": "ANDROID_VR", "clientVersion": "1.65.10",
            "deviceMake": "Oculus", "deviceModel": "Quest 3",
            "androidSdkVersion": 32, "osName": "Android", "osVersion": "12L",
            "hl": "en", "gl": "US", "visitorData": visitor,
        }, {"X-Youtube-Client-Name": "28"}, None),
        ("web_embedded", {
            "clientName": "WEB_EMBEDDED_PLAYER", "clientVersion": "1.20260115.01.00",
            "hl": "en", "gl": "US", "visitorData": visitor,
        }, {"X-Youtube-Client-Name": "56"},
            {"thirdParty": {"embedUrl": f"https://www.youtube.com/watch?v={vid}"}}),
    )


def extract_id(value: str) -> str | None:
    """11-char video id from any watch/share/shorts/embed URL, or a bare id."""
    m = _ID_RE.search(value)
    if m:
        return m.group(1)
    value = value.strip()
    return value if _BARE_ID_RE.fullmatch(value) else None


async def _post(vid: str, client: dict, headers: dict, ctx_extra: dict | None) -> dict:
    body = orjson.dumps({"videoId": vid, "context": {"client": client, **(ctx_extra or {})}})
    r = await _client.post(_URL, content=body, headers={
        "Content-Type": "application/json", "User-Agent": _ANDROID_UA, **headers,
    })
    r.raise_for_status()
    return orjson.loads(r.content)


async def _player_data(url_or_id: str) -> dict | None:
    """Player response from the first client that reports a playable video, else None."""
    vid = extract_id(url_or_id)
    if not vid:
        return None

    android = {"clientName": "ANDROID", "clientVersion": "20.10.38",
               "androidSdkVersion": 30, "hl": "en", "gl": "US"}
    try:
        data = await _post(vid, android, {"X-Youtube-Client-Name": "3"}, None)
    except Exception as e:
        logger.warning(f"[INNERTUBE] android client failed for {vid}: {e}")
        return None

    if (data.get("playabilityStatus") or {}).get("status") == "OK":
        return data

    visitor = (data.get("responseContext") or {}).get("visitorData")
    for label, client, headers, ctx_extra in _ladder(vid, visitor):
        try:
            alt = await _post(vid, client, headers, ctx_extra)
        except Exception:  # dead client version / HTTP error -> try the next
            continue
        if (alt.get("playabilityStatus") or {}).get("status") == "OK":
            logger.info(f"[INNERTUBE] {vid} recovered via {label}")
            return alt

    reason = (data.get("playabilityStatus") or {}).get("reason") or "not playable"
    logger.info(f"[INNERTUBE] {vid} unavailable anonymously ({reason}) — falling back")
    return None


async def _streaming_data(url_or_id: str) -> dict | None:
    data = await _player_data(url_or_id)
    return (data.get("streamingData") or None) if data else None


def _by_itag(fmts: list, itag: int) -> str | None:
    for f in fmts:
        if f.get("itag") == itag and f.get("url"):
            return f["url"]
    return None


def _pick_audio(sd: dict) -> str | None:
    """Mirrors `-f 251/250/bestaudio[ext=m4a]/bestaudio`."""
    adaptive = [f for f in sd.get("adaptiveFormats") or [] if f.get("url")]
    for itag in (251, 250):
        url = _by_itag(adaptive, itag)
        if url:
            return url
    audio = [f for f in adaptive if (f.get("mimeType") or "").startswith("audio/")]
    if not audio:
        return None
    m4a = [f for f in audio if "mp4" in (f.get("mimeType") or "")]
    return max(m4a or audio, key=lambda f: f.get("bitrate") or 0)["url"]


def _pick_muxed(sd: dict) -> str | None:
    """Mirrors `-f 22/18/best[ext=mp4]` — single-file audio+video."""
    formats = [f for f in sd.get("formats") or [] if f.get("url")]
    for itag in (22, 18):
        url = _by_itag(formats, itag)
        if url:
            return url
    if not formats:
        return None
    mp4 = [f for f in formats if "mp4" in (f.get("mimeType") or "")]
    return max(mp4 or formats, key=lambda f: f.get("height") or 0)["url"]


_PICKERS = {"audio": _pick_audio, "muxed": _pick_muxed}


async def resolve(url_or_id: str, kind: str) -> str | None:
    """One stream URL, or None to tell the caller to fall back. kind: audio|muxed."""
    sd = await _streaming_data(url_or_id)
    return _PICKERS[kind](sd) if sd else None


async def resolve_both(url_or_id: str) -> tuple[str | None, str | None]:
    """(muxed, audio) from a SINGLE player call — replaces two yt-dlp subprocesses."""
    sd = await _streaming_data(url_or_id)
    if not sd:
        return None, None
    return _pick_muxed(sd), _pick_audio(sd)


async def metadata(url_or_id: str) -> dict | None:
    """Video metadata shaped like utils.youtube_api.GetVideoById, or None to fall back.

    Same player call the stream picks come from, so the no-API-key path costs one
    HTTP request instead of a `yt-dlp -j` subprocess.
    """
    data = await _player_data(url_or_id)
    if not data:
        return None
    d = data.get("videoDetails") or {}
    vid = d.get("videoId")
    if not vid or not d.get("title"):
        return None

    from .formatters import extract_artist
    from .helpers import format_ind

    secs = int(d.get("lengthSeconds") or 0)
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    channel = d.get("author") or ""
    thumbs = (d.get("thumbnail") or {}).get("thumbnails") or []

    return {
        "title": d.get("title", ""),
        "url": f"https://www.youtube.com/watch?v={vid}",
        "artist_name": extract_artist(d.get("title", "")) or channel,
        "channel_name": channel,
        "views": format_ind(int(d.get("viewCount") or 0)),
        "duration": f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}",
        "thumbnail": thumbs[-1].get("url", "") if thumbs else "",
        "video_id": vid,
    }


async def close_client() -> None:
    await _client.aclose()

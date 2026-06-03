import httpx
import os
import random
import asyncio
from .formatters import format_dur, process_video, extract_artist
from .helpers import parse_dur, format_ind


SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
DETAILS_URL = "https://www.googleapis.com/youtube/v3/videos"


def get_available_keys():
    raw = os.getenv("YOUTUBE_API_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return keys


def get_random_key():
    keys = get_available_keys()
    if not keys:
        raise RuntimeError("YouTube API key not configured")
    return random.choice(keys)


async def fetch_results(query: str, limit: int = 1):
    keys = get_available_keys()
    if not keys:
        return []

    async with httpx.AsyncClient(timeout=10) as client:
        api_key = get_random_key()

        search_params = {
            "part": "snippet",
            "q": query,
            "maxResults": limit,
            "type": "video",
            "key": api_key,
        }

        search_res = await client.get(SEARCH_URL, params=search_params)
        if search_res.status_code != 200:
            return []

        items = search_res.json().get("items", [])
        video_ids = [item["id"]["videoId"] for item in items if "videoId" in item.get("id", {})]

        if not video_ids:
            return []

        api_key = get_random_key()

        details_params = {
            "part": "contentDetails,statistics",
            "id": ",".join(video_ids),
            "key": api_key,
        }

        detail_res = await client.get(DETAILS_URL, params=details_params)
        if detail_res.status_code != 200:
            return []

        detail_items = {
            v["id"]: v for v in detail_res.json().get("items", [])
        }

        results = []

        for item in items:
            video_id = item["id"].get("videoId")
            if not video_id:
                continue

            video_details = detail_items.get(video_id)
            if not video_details:
                continue

            video_info = process_video(item, video_details)
            if video_info:
                results.append(video_info)

        return results


async def GetVideoById(video_id: str):
    keys = get_available_keys()
    if not keys:
        # Fallback to extracting using yt-dlp -j (no API key needed)
        try:
            cmd = [
                "yt-dlp",
                "--js-runtimes", "node",
                "--remote-components", "ejs:github",
                "-j",
                f"https://www.youtube.com/watch?v={video_id}"
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=40,
            )
            if process.returncode == 0 and stdout:
                import json as _json
                info = _json.loads(stdout.decode().strip())
                title = info.get("title", "")
                uploader = info.get("uploader", "")
                duration_sec = info.get("duration", 0) or 0
                
                # Format duration_sec to string
                h = duration_sec // 3600
                m = (duration_sec % 3600) // 60
                s = duration_sec % 60
                duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

                views = info.get("view_count", 0) or 0
                thumbnail = info.get("thumbnail", "")

                artist = extract_artist(title) or uploader

                return {
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "artist_name": artist,
                    "channel_name": uploader,
                    "views": format_ind(views),
                    "duration": duration_str,
                    "thumbnail": thumbnail,
                    "video_id": video_id,
                }
        except Exception as e:
            # log warning
            pass
        return {}

    async with httpx.AsyncClient(timeout=10) as client:
        api_key = get_random_key()

        params = {
            "part": "snippet,contentDetails,statistics",
            "id": video_id,
            "key": api_key,
        }

        res = await client.get(DETAILS_URL, params=params)
        if res.status_code != 200:
            return {}

        items = res.json().get("items", [])
        if not items:
            return {}

        item = items[0]
        snippet = item.get("snippet", {})
        title = snippet.get("title", "")
        channel = snippet.get("channelTitle", "")
        thumbnail = (
            snippet.get("thumbnails", {})
            .get("high", {})
            .get("url", "")
        )
        duration = (
            item.get("contentDetails", {})
            .get("duration", "N/A")
        )
        views = (
            item.get("statistics", {})
            .get("viewCount", "0")
        )
        artist = extract_artist(title) or channel

        return {
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "artist_name": artist,
            "channel_name": channel,
            "views": format_ind(views),
            "duration": parse_dur(duration),
            "thumbnail": thumbnail,
            "video_id": video_id,
        }

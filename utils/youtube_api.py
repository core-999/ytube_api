import httpx
import os
import random
from .formatters import format_dur, process_video


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

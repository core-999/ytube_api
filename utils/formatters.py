from .helpers import parse_dur, format_ind


def format(n):
    return format_ind(n)


def format_dur(duration_str):
    return parse_dur(duration_str)


def process_video(item, details):
    try:
        video_id = item["id"]["videoId"]
        snippet = item.get("snippet", {})

        title = snippet.get("title", "")
        channel = snippet.get("channelTitle", "")
        thumbnail = (
            snippet.get("thumbnails", {})
            .get("high", {})
            .get("url", "")
        )

        url = f"https://www.youtube.com/watch?v={video_id}"

        duration = (
            details.get("contentDetails", {})
            .get("duration", "N/A")
        )

        views = (
            details.get("statistics", {})
            .get("viewCount", "0")
        )

        artist = extract_artist(title) or channel

        return {
            "title": title,
            "url": url,
            "artist_name": artist,
            "channel_name": channel,
            "views": format(views),
            "duration": format_dur(duration),
            "thumbnail": thumbnail,
        }

    except Exception:
        return None


def extract_artist(title: str):
    if "-" in title:
        name = title.split("-", 1)[0].strip()
        if name:
            return name
    return "Unknown Artist"

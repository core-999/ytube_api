import re
import urllib.parse as urlparse


def extract_playlist_id(url: str) -> str:
    query = urlparse.urlparse(url).query
    params = urlparse.parse_qs(query)
    return params.get("list", [""])[0]


def parse_dur(duration: str) -> str:
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        duration or "",
    )

    if not match:
        return "N/A"

    hours, minutes, seconds = match.groups(default="0")

    h = int(hours)
    m = int(minutes)
    s = int(seconds)

    if h:
        return f"{h}:{m:02d}:{s:02d}"

    return f"{m}:{s:02d}"


def format_ind(n):
    try:
        n = float(n)
    except (ValueError, TypeError):
        return "0"

    if n >= 10**7:
        return f"{n / 10**7:.1f} Crore"

    if n >= 10**5:
        return f"{n / 10**5:.1f} Lakh"

    if n >= 10**3:
        return f"{n / 10**3:.1f}K"

    return str(int(n))


def format_views(views_str: str):
    if not views_str:
        return "N/A"

    cleaned = "".join(filter(str.isdigit, views_str))

    if not cleaned:
        return "N/A"

    try:
        value = float(cleaned)
    except ValueError:
        return "N/A"

    if "M" in views_str:
        value *= 10**6
    elif "K" in views_str:
        value *= 10**3

    return format_ind(value)

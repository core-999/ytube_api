from .youtube_api import fetch_results as YtSearch
from .search_service import fetch_results as Search, close_client
from .cache_manager import get_stream, get_video_stream
from .media_extractor import resolve_stream_urls as get_video_audio_urls, mux_streams as stream_merged
from .formatters import format_dur, process_video, extract_artist
from .helpers import parse_dur, format_ind, format_views

__version__ = "2026.3.05"
__author__ = "DEBLOMPER"

__all__ = [
    "YtSearch",
    "Search",
    "close_client",
    "get_stream",
    "get_video_stream",
    "get_video_audio_urls",
    "stream_merged",
    "format_dur",
    "process_video",
    "extract_artist",
    "parse_dur",
    "format_ind",
    "format_views",
]

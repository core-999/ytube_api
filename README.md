# yt-dlp_api

A high-performance, asynchronous web API and Telegram bot ecosystem for YouTube search, metadata extraction, playlist parsing, and audio/video stream URL resolution. 

This repository provides a unified FastAPI backend and a Pyrogram-based Telegram bot. It features native integration with Redis for caching and rate limiting, and uses Deno for solving YouTube EJS signature challenges.

---

## Features

- ⚡ **High Performance & Async**: Fully asynchronous API built on FastAPI, Uvicorn, and Pyrogram.
- 🚀 **Advanced Stream Extraction**: Resolves direct video and audio streams via `yt-dlp` using optimized player client parameters.
- 🇩 **EJS Challenge Solver**: Integrated Deno JS runtime inside the container to solve complex YouTube EJS signature challenges dynamically.
- 🗄️ **Redis Caching**: Caches stream metadata, resolving configurations, and rates to minimize latency and avoid YouTube rate limits.
- 🔒 **Token-Based Rate Limiting**: Automatic user rate limiting managed via a Redis-backed token system.
- 🤖 **Telegram Bot Management**: Simple Telegram bot for users to generate tokens, check limits, and for admins to manage users, customize rate limits, broadcast messages, and view real-time API logs.
- 🐳 **Docker-Compose Ready**: Easy, zero-config deployment using Docker Compose.

---

## Architecture Overview

```text
               +-----------------------+
               |  FastAPI Web Service  | <--- REST API Clients
               +-----------------------+
                           |
                           v
+--------------+     +-----------+     +-------------------+
| Telegram Bot | --> |   Redis   | <-- | yt_dlp_api Module |
+--------------+     +-----------+     +-------------------+
  (User/Token          (Rate Limits          (Search, Stream
   Management)          & Caching)            & Playlist Parsing)
                                             |
                                             v
                                       +-------------+
                                       | Deno / Yt   |
                                       +-------------+
```

---

## Quick Start (Docker Deployment)

The easiest way to run the entire stack (FastAPI, Telegram Bot, Redis) is using Docker Compose.

### 1. Prerequisites
Ensure you have [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed.

### 2. Configure Environment Variables
Create a `.env` file in the root directory and configure your credentials:

```ini
# Telegram Bot API Credentials
API_ID=21856699
API_HASH=73f10cf0979637857170f03d4c86f251
BOT_TOKEN=your_bot_token

# Redis Configuration (Optional: default uses redis service container)
REDIS_HOST=redis
REDIS_PORT=6379

# API Rate Limits
DAILY_LIMIT=1000
ADMIN_LIMIT=10000
```

### 3. Run the Services
Start the application stack:

```bash
docker-compose up --build -d
```

This will spin up:
- **FastAPI Web API** on port `8000`
- **Telegram Bot** runner
- **Redis Cache Database**

---

## Manual Installation (Local Development)

If you prefer to run the services locally without Docker:

### 1. Install System Dependencies
- Install **FFmpeg** (required by `yt-dlp` for media processing).
- Install **Deno** (required for solving signature challenges):
  ```bash
  curl -fsSL https://deno.land/install.sh | sh
  ```

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the Services
Run the Redis server locally, and then start the API and Bot separately:

```bash
# Start the Web API
python3 main.py

# Start the Telegram Bot
python3 bot.py
```

---

## Configuration Reference

All secrets and tunables are centralised in `config.py` and can be customized via environment variables:

| Environment Variable | Description | Default |
|----------------------|-------------|---------|
| `API_ID` | Telegram API ID (from my.telegram.org) | `21856699` |
| `API_HASH` | Telegram API Hash (from my.telegram.org) | `73f10cf09796...` |
| `BOT_TOKEN` | Token for the Pyrogram bot | `8246299769...` |
| `TG_GROUP` | Telegram support/discussion group username | `nub_coder_s` |
| `TG_CHANNEL` | Telegram news/update channel username | `nub_coders` |
| `REDIS_HOST` | Hostname of the Redis server | `redis-15440...` |
| `REDIS_PORT` | Port of the Redis server | `15440` |
| `REDIS_USERNAME`| Username for Redis authentication | `default` |
| `REDIS_PASSWORD`| Password for Redis authentication | `Af1Y9RyLA...` |
| `DAILY_LIMIT` | Default daily requests limit for free tier users | `1000` |
| `ADMIN_LIMIT` | Default daily requests limit for administrators | `10000` |

---

## Web API Endpoints

The web API is served at `http://localhost:8000`. By default, public endpoints are free, while data-heavy parsing endpoints require an authentication token generated via the Telegram Bot.

### Public Endpoints

#### `GET /health`
Returns service health status.
- **Response**: `{"status": "healthy"}`

#### `GET /`
Returns service info, endpoint directory, and redirects configuration.

#### `GET /search`
Perform queries on YouTube / YouTube Music.
- **Parameters**:
  - `q` (string, required): Query term.
  - `limit` (integer, optional): Maximum results. Default `10`.
- **Response**: Main results and list items.

#### `GET /trending`
Get trending music tracks.
- **Parameters**:
  - `limit` (integer, optional): Maximum results. Default `20`.

#### `GET /suggest`
Get search completion suggestions for a partial query.
- **Parameters**:
  - `q` (string, required): Partial query.
  - `limit` (integer, optional): Maximum suggestions. Default `10`.

---

### Authenticated Endpoints
*Must include header: `token: YOUR_TELEGRAM_BOT_TOKEN`*

#### `GET /rate-limit-status`
Check your current token request usage and remaining quota.

#### `GET /info`
Get raw metadata information of a specific YouTube video.
- **Parameters**:
  - `video_id` (string, required): YouTube video ID.

#### `GET /stream`
Resolve and return direct audio stream URLs.
- **Parameters**:
  - `url` (string, required): YouTube video URL or ID.
- **Response**: `{"url": "DIRECT_AUDIO_STREAM_URL"}`

#### `GET /video-stream`
Resolve and return both video and audio stream URLs.
- **Parameters**:
  - `url` (string, required): YouTube video URL or ID.
- **Response**: `{"video_url": "...", "audio_url": "..."}`

#### `GET /playlist`
Parse all video tracks in a playlist.
- **Parameters**:
  - `url` (string, required): YouTube Playlist URL or ID.

---

## Telegram Bot Interface

Users must message the Telegram bot (e.g. `@ytdlp_nub_bot`) to obtain an API token and manage their usage.

### User Commands
- `/start` - Authenticates user, creates account, and issues an API token.
- `/menu` - Interactive inline button interface for checking rates and profile.
- `/token` - Displays the user's active API token.
- `/status` - Checks current rate limits, tier, and requested endpoint counts.
- `/ping` - Latency ping check with bot uptime statistics.

### Administrative Commands
- `/stats` - Comprehensive API performance dashboard (requests, uptime, user tiers, active logs).
- `/user <tg_id>` - Inspect usage statistics and rate limit status of a specific user.
- `/grant <tg_id> <limit>` - Set custom daily rate limit for a specific user.
- `/revoke <tg_id>` - Reset custom rate limit for a user back to default.
- `/listusers` - List all registered user IDs.
- `/errors` - Display recent API 4xx/5xx failure logs with details.
- `/broadcast <msg>` - Send an announcement message to all registered bot users.
- `/adminhelp` - Show helper card for all administrative commands.

---

## Using `yt_dlp_api` in Code

If you prefer to import the modules programmatically inside other Python scripts, use the `yt_dlp_api` package:

```python
import asyncio
from utils.search_service import fetch_results
from utils.cache_manager import get_stream

async def main():
    # 1. Search song
    results = await fetch_results("Kesariya", limit=1)
    if results and results.get("main_results"):
        song = results["main_results"][0]
        print(f"Found: {song['title']} by {song['channel']}")
        
        # 2. Extract direct stream URL
        stream_url = await get_stream(song['url'])
        print(f"Direct stream URL: {stream_url}")

asyncio.run(main())
```

---

## Project Structure

```text
yt-dlp_api/
│
├── config.py              # Centralised environment variable loader
├── main.py                # FastAPI endpoints and middleware
├── bot.py                 # Pyrogram client initializer
├── tools.py               # Redis client connection and token handlers
│
├── yt_dlp_api/            # Core library python package
│   ├── __init__.py
│   ├── Search.py          # Scraping-based search functions
│   ├── YtSearch.py        # YouTube Data API backup search
│   ├── Stream.py          # Audio stream extraction
│   ├── Video_Stream.py    # Video stream extraction
│   ├── Playlist.py        # Playlist parser
│   ├── Models.py          # JSON payload models
│   ├── Utils.py           # Helper utilities
│   └── cli.py             # CLI commands
│
└── plugins/               # Telegram bot pyrogram plugins
    ├── admin.py           # Administrative stats, limits, and error logs
    ├── broadcast.py       # Global bot broadcast dispatcher
    ├── commands.py        # Menu, ping, start commands
    └── status.py          # User profile status and tokens
```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

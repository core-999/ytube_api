from pyrogram import filters
from pyrogram.client import Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import asyncio
import time


# Import from tools module
from tools import (
    redis_client, generate_token, is_admin, get_user_token, 
    set_user_token, revoke_user_token, get_user_request_count,
    set_user_request_count, increment_user_requests
)

BOT_START_TIME = time.time()

def get_readable_time(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d > 0:
        return f"{d}d {h}h {m}m {s}s"
    elif h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

@Client.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    if not message.from_user:
        return

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    # Check if user already has a token
    existing_token = await get_user_token(user_id)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔧 API Implementation", callback_data="api_implementation"),
            InlineKeyboardButton("📊 Usage Status", callback_data="usage_status")
        ],
        [
            InlineKeyboardButton("🔄 Revoke Token", callback_data="revoke_token"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ]
    ])

    if existing_token:
        await message.reply_text(
            f"🎉 **Welcome back, {username}!**\n\n"
            f"✅ Your API is ready to use!\n"
            f"🔗 Token: `{existing_token}`\n\n"
            f"🌐 **API Base URL:**\n"
            f"`http://api.nubcoder.com/`\n\n"
            f"📝 **Usage:**\n"
            f"Add your token as a query parameter:\n"
            f"`http://api.nubcoder.com/info?token={existing_token}&q=VIDEO_URL`\n\n"
            f"📈 **Daily Limit:** 1000 requests\n"
            f"🔍 **Search:** Always free!",
            reply_markup=keyboard
        )
    else:
        # Generate new token
        new_token = generate_token()
        await set_user_token(user_id, new_token)

        await message.reply_text(
            f"🎉 **Welcome to YT-DLP API, {username}!**\n\n"
            f"🔑 Your API token: `{new_token}`\n\n"
            f"🌐 **API Base URL:**\n"
            f"`http://api.nubcoder.com/`\n\n"
            f"📝 **How to use:**\n"
            f"Add your token as a query parameter:\n"
            f"`http://api.nubcoder.com/info?token={new_token}&q=VIDEO_URL`\n\n"
            f"📈 **Daily Limit:** 1000 requests\n"
            f"🔍 **Search:** Always free!\n\n"
            f"🚀 **Get started:** Use the buttons below!",
            reply_markup=keyboard
        )

@Client.on_message(filters.command("menu"))
async def menu_command(client: Client, message: Message):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔧 API Implementation", callback_data="api_implementation"),
            InlineKeyboardButton("📊 Usage Status", callback_data="usage_status")
        ],
        [
            InlineKeyboardButton("🔄 Revoke Token", callback_data="revoke_token"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ],
        [
            InlineKeyboardButton("📖 API Docs", callback_data="api_docs")
        ]
    ])

    await message.reply_text(
        "🤖 **YT-DLP API Bot Menu**\n\n"
        "Choose an option below:",
        reply_markup=keyboard
    )

@Client.on_message(filters.command("ping"))
async def ping_command(client: Client, message: Message):
    """Measure and display bot latency and uptime"""
    start = time.time()
    sent = await message.reply_text("🏓 Pong!")
    elapsed = round((time.time() - start) * 1000, 2)
    uptime = get_readable_time(int(time.time() - BOT_START_TIME))
    await sent.edit_text(f"🏓 **Pong!**\n\n⚡ **Latency:** `{elapsed} ms`\n⏱ **Uptime:** `{uptime}`")

@Client.on_callback_query()
async def handle_callbacks(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if data == "api_implementation":
        token = await get_user_token(user_id)
        if token:
            await callback_query.answer()
            await callback_query.edit_message_text(
                f"🔧 **API Implementation Guide**\n\n"
                f"🔑 **Your Token:** `{token}`\n\n"
                f"Choose implementation method:",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🌐 GET Examples", callback_data="impl_get_all"),
                        InlineKeyboardButton("🐍 Python Implement", callback_data="impl_python_all")
                    ],
                    [
                        InlineKeyboardButton("📋 Quick Reference", callback_data="impl_quick_ref"),
                        InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")
                    ]
                ])
            )
        else:
            await callback_query.answer("❌ No token found. Use /start to generate one.", show_alert=True)

    elif data == "usage_status":
        token = await get_user_token(user_id)
        if not token:
            await callback_query.answer("❌ No token found. Use /start to get one.", show_alert=True)
            return

        request_count = await get_user_request_count(user_id)
        limit = 10000 if is_admin(user_id) else 1000
        remaining = max(0, limit - request_count)

        status_text = (
            f"📊 **Usage Statistics**\n\n"
            f"🔑 Token: `{token}`\n"
            f"📈 Used today: **{request_count}**/{limit}\n"
            f"📉 Remaining: **{remaining}**\n"
            f"🕒 Reset: Midnight UTC\n"
        )

        if is_admin(user_id):
            status_text += "\n👑 **Admin privileges active**"

        # Progress bar
        progress = int((request_count / limit) * 10)
        bar = "🟩" * progress + "⬜" * (10 - progress)
        status_text += f"\n\n📊 Progress: {bar}"

        await callback_query.answer()
        await callback_query.edit_message_text(
            status_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="usage_status")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
            ])
        )

    elif data == "revoke_token":
        await callback_query.answer()
        await callback_query.edit_message_text(
            "⚠️ **Are you sure?**\n\n"
            "This will revoke your current token and generate a new one.\n"
            "You'll need to update all your API calls with the new token.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes, Revoke", callback_data="confirm_revoke"),
                    InlineKeyboardButton("❌ Cancel", callback_data="back_menu")
                ]
            ])
        )

    elif data == "confirm_revoke":
        # Revoke old token
        await revoke_user_token(user_id)

        # Generate new token
        new_token = generate_token()
        await set_user_token(user_id, new_token)

        await callback_query.answer("✅ Token revoked successfully!")
        await callback_query.edit_message_text(
            f"✅ **Token Revoked Successfully!**\n\n"
            f"🔑 Your new token: `{new_token}`\n\n"
            f"⚠️ **Important:** Update your API calls with the new token immediately.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
            ])
        )

    elif data == "help":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "❓ **Help & Commands**\n\n"
            "🤖 **Bot Commands:**\n"
            "• `/start` - Get your API token\n"
            "• `/menu` - Show main menu\n"
            "• `/status` - Check usage status\n"
            "• `/token` - View current token\n"
            "• `/revoke` - Revoke current token\n\n"
            "🌐 **API Base URL:**\n"
            "`http://api.nubcoder.com/`\n\n"
            "🔗 **API Endpoints:**\n"
            "• `/info` - Get video info + streamable URL (requires token)\n"
            "• `/search` - Search videos (free, no URLs)\n"
            "\n"
            "• `/health` - Health check\n\n"
            "📝 **Usage:**\n"
            f"Example: `http://api.nubcoder.com/info?token={user_token}&q=VIDEO_URL`\n\n"
            "🐍 **Python Example:**\n"
            "```python\n"
            "import requests\n"
            "response = requests.get(\n"
            "    'http://api.nubcoder.com/info',\n"
            f"    params={{'token': '{user_token}', 'q': 'VIDEO_URL'}}\n"
            ")\n"
            "data = response.json()\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📖 API Docs", callback_data="api_docs")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
            ])
        )

    elif data == "impl_get_all":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🌐 **All API Endpoints - GET Examples**\n\n"
            "**1. Video Info:**\n"
            "```\n"
            f"GET http://api.nubcoder.com/info?token={user_token}&q=https://youtube.com/watch?v=dQw4w9WgXcQ\n"
            "```\n\n"
            "**2. Search Videos (Free):**\n"
            "```\n"
            f"GET http://api.nubcoder.com/search?q=python tutorial&max_results=5\n"
            "```\n\n"
            "**4. Rate Limit Status:**\n"
            "```\n"
            f"GET http://api.nubcoder.com/rate-limit-status?token={user_token}\n"
            "```\n\n"
            "**5. Health Check:**\n"
            "```\n"
            "GET http://api.nubcoder.com/health\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation")]
            ])
        )

    elif data == "impl_python_all":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🐍 **Complete Python Implementation**\n\n"
            "```python\n"
            "import requests\n"
            "import json\n"
            "import time\n"
            "from typing import List, Dict, Optional, Tuple\n"
            "from datetime import datetime\n\n"
            f"API_TOKEN = '{user_token}'\n"
            "BASE_URL = 'http://api.nubcoder.com'\n\n"
            "def get_video_info(url_or_query: str, max_results: int = 1) -> Tuple[str, str, int, str, str, int, str, str, str]:\n"
            "    \"\"\"Get video info - returns (title, video_id, duration, youtube_link, channel_name, views, stream_url, thumbnail, time_taken)\"\"\"\n"
            "    try:\n"
            "        response = requests.get(\n"
            "            f'{BASE_URL}/info',\n"
            "            params={'token': API_TOKEN, 'q': url_or_query, 'max_results': max_results},\n"
            "            timeout=30\n"
            "        )\n"
            "        response.raise_for_status()\n"
            "        data = response.json()\n"
            "        \n"
            "        if 'error' in data:\n"
            "            return None, None, None, None, None, None, None, data.get('error')\n"
            "        \n"
            "        return (\n"
            "            data.get('title', 'N/A'),\n"
            "            data.get('video_id', 'N/A'),\n"
            "            data.get('duration', 0),\n"
            "            data.get('youtube_link', 'N/A'),\n"
            "            data.get('channel_name', 'N/A'),\n"
            "            data.get('views', 0),\n"
            "            data.get('url', 'N/A'),\n"
            "            data.get('thumbnail', 'N/A'),\n"
            "            data.get('time_taken', 'N/A')\n"
            "        )\n"
            "    except requests.RequestException as e:\n"
            "        return None, None, None, None, None, None, None, str(e)\n\n"
            "def search_videos(query: str, max_results: int = 5) -> List[Tuple[str, str, str, int, int, str]]:\n"
            "    \"\"\"Search videos - returns list of (title, video_id, channel_name, duration, views, youtube_link)\"\"\"\n"
            "    try:\n"
            "        response = requests.get(\n"
            "            f'{BASE_URL}/search',\n"
            "            params={'q': query, 'max_results': max_results},\n"
            "            timeout=30\n"
            "        )\n"
            "        response.raise_for_status()\n"
            "        data = response.json()\n"
            "        \n"
            "        if 'error' in data:\n"
            "            return []\n"
            "        \n"
            "        results = []\n"
            "        for video in data.get('results', []):\n"
            "            results.append((\n"
            "                video.get('title', 'N/A'),\n"
            "                video.get('video_id', 'N/A'),\n"
            "                video.get('channel_name', 'N/A'),\n"
            "                video.get('duration', 0),\n"
            "                video.get('views', 0),\n"
            "                video.get('youtube_link', 'N/A')\n"
            "            ))\n"
            "        return results\n"
            "    except requests.RequestException as e:\n"
            "        return []\n\n"
            "def get_rate_limit_status() -> Tuple[int, int, int, bool, str]:\n"
            "    \"\"\"Get quota status - returns (daily_limit, requests_used, requests_remaining, is_admin, reset_time)\"\"\"\n"
            "    try:\n"
            "        response = requests.get(\n"
            "            f'{BASE_URL}/rate-limit-status',\n"
            "            params={'token': API_TOKEN},\n"
            "            timeout=10\n"
            "        )\n"
            "        response.raise_for_status()\n"
            "        data = response.json()\n"
            "        \n"
            "        return (\n"
            "            data.get('daily_limit', 0),\n"
            "            data.get('requests_used', 0),\n"
            "            data.get('requests_remaining', 0),\n"
            "            data.get('is_admin', False),\n"
            "            data.get('reset_time', 'N/A')\n"
            "        )\n"
            "    except requests.RequestException as e:\n"
            "        return 0, 0, 0, False, str(e)\n\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation")]
            ])
        )

    elif data == "impl_quick_ref":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "📋 **Quick Reference**\n\n"
            f"🔑 **Token:** `{user_token}`\n"
            f"🌐 **Base URL:** `http://api.nubcoder.com`\n\n"
            "**Endpoints:**\n"
            f"• `/info?token={user_token}&q=URL` - ✅ Video info + STREAM URL\n"
            "• `/search?q=QUERY&max_results=5` - ❌ Search only (NO STREAM)\n"
            f"• `/rate-limit-status?token={user_token}` - Quota\n"
            "• `/health` - Health check\n\n"
            "**Rate Limits:**\n"
            "• Data endpoints: 1000/day\n"
            "• Search: Unlimited\n"
            "• Batch: Max 5 URLs per request\n\n"
            "**Python Quick Start:**\n"
            "```python\n"
            "import requests\n"
            f"r = requests.get('http://api.nubcoder.com/info?token={user_token}&q=VIDEO_URL')\n"
            "data = r.json()\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation")]
            ])
        )

    elif data == "api_docs":
        await callback_query.answer()
        await callback_query.edit_message_text(
            "📖 **API Documentation**\n\n"
            "🔗 **Base URL:** `http://api.nubcoder.com/`\n\n"
            "📝 **Authentication:**\n"
            "Add your token as query parameter:\n"
            "```\n"
            "?token=YOUR_TOKEN\n"
            "```\n\n"
            "📊 **Rate Limits:**\n"
            "• Data endpoints: 1000/day\n"
            "• Search: Unlimited\n\n"
            "Select an endpoint to view detailed documentation:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎥 Video Info", callback_data="api_info"),
                    InlineKeyboardButton("🔍 Search", callback_data="api_search")
                ],
                [
                    InlineKeyboardButton("📊 Rate Limit", callback_data="api_ratelimit"),
                    InlineKeyboardButton("❤️ Health Check", callback_data="api_health")
                ],
                [
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")
                ]
            ])
        )

    elif data == "api_info":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🎥 **Video Info Endpoint**\n\n"
            "**Endpoint:** `http://api.nubcoder.com/info`\n"
            "**Method:** `GET`\n"
            "**Auth:** Token required\n"
            "**Returns:** ✅ Video metadata + **DIRECT STREAM URL**\n\n"
            "**Parameters:**\n"
            "• `token` - Your API token\n"
            "• `q` - YouTube URL or search query\n"
            "• `max_results` - Max results (for search)\n\n"
            "Select example type:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌐 GET Examples", callback_data="api_info_get"),
                    InlineKeyboardButton("🐍 Python Implementation", callback_data="api_info_python")
                ],
                [InlineKeyboardButton("🔙 Back to API Docs", callback_data="api_docs")]
            ])
        )

    elif data == "api_info_get":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🌐 **Video Info - GET Examples**\n\n"
            "**1. Get info by URL:**\n"
            "```\n"
            f"GET http://api.nubcoder.com/info?token={user_token}&q=https://youtube.com/watch?v=dQw4w9WgXcQ\n"
            "```\n\n"
            "**2. Search single video:**\n"
            "```\n"
            f"GET http://api.nubcoder.com/info?token={user_token}&q=python tutorial&max_results=1\n"
            "```\n\n"
            "**3. Search multiple videos:**\n"
            "```\n"
            f"GET http://api.nubcoder.com/info?token={user_token}&q=machine learning&max_results=5\n"
            "```\n\n"
            "**4. Using curl:**\n"
            "```bash\n"
            f"curl \"http://api.nubcoder.com/info?token={user_token}&q=https://youtube.com/watch?v=VIDEO_ID\"\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Video Info", callback_data="api_info")]
            ])
        )

    elif data == "api_info_python":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🐍 **Video Info - Python Implementation**\n\n"
            "```python\n"
            "import requests\n"
            "import json\n\n"
            f"TOKEN = '{user_token}'\n"
            "BASE = 'http://api.nubcoder.com'\n\n"
            "def get_video_info(url_or_query, max_results=1):\n"
            "    \"\"\"Get detailed video information\"\"\"\n"
            "    params = {\n"
            "        'token': TOKEN,\n"
            "        'q': url_or_query,\n"
            "        'max_results': max_results\n"
            "    }\n"
            "    \n"
            "    try:\n"
            "        response = requests.get(f'{BASE}/info', params=params, timeout=30)\n"
            "        response.raise_for_status()\n"
            "        \n"
            "        data = response.json()\n"
            "        \n"
            "        if 'error' in data:\n"
            "            print(f\"API Error: {data['error']}\")\n"
            "            return None\n"
            "        \n"
            "        return data\n"
            "        \n"
            "    except requests.exceptions.Timeout:\n"
            "        print(\"Request timed out\")\n"
            "    except requests.exceptions.HTTPError as e:\n"
            "        if response.status_code == 429:\n"
            "            print(\"Rate limit exceeded\")\n"
            "        elif response.status_code == 401:\n"
            "            print(\"Invalid token\")\n"
            "        else:\n"
            "            print(f\"HTTP Error: {e}\")\n"
            "    except Exception as e:\n"
            "        print(f\"Error: {e}\")\n"
            "    \n"
            "    return None\n\n"
            "# Usage examples:\n"
            "# By URL\n"
            "video_info = get_video_info('https://youtube.com/watch?v=dQw4w9WgXcQ')\n"
            "if video_info:\n"
            "    print(f\"Title: {video_info['title']}\")\n"
            "    print(f\"Duration: {video_info['duration']} seconds\")\n"
            "    print(f\"Views: {video_info.get('views', 'N/A')}\")\n"
            "    print(f\"Stream URL: {video_info['url']}\")\n"
            "    print(f\"Thumbnail: {video_info['thumbnail']}\")\n\n"
            "# By search query\n"
            "search_result = get_video_info('python tutorial', max_results=1)\n"
            "if search_result:\n"
            "    print(f\"Found: {search_result['title']}\")\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Video Info", callback_data="api_info")]
            ])
        )

    elif data == "api_search":
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🔍 **Search Endpoint** (FREE)\n\n"
            "**Endpoint:** `http://api.nubcoder.com/search`\n"
            "**Method:** `GET`\n"
            "**Auth:** No token required\n"
            "**Returns:** ❌ Metadata only (NO STREAM URLs)\n\n"
            "**Parameters:**\n"
            "• `q` - Search query\n"
            "• `max_results` - Number of results (1-20)\n\n"
            "Select example type:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌐 GET Examples", callback_data="api_search_get"),
                    InlineKeyboardButton("🐍 Python Implementation", callback_data="api_search_python")
                ],
                [InlineKeyboardButton("🔙 Back to API Docs", callback_data="api_docs")]
            ])
        )

    elif data == "api_search_get":
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🌐 **Search - GET Examples**\n\n"
            "**1. Basic search (1 result):**\n"
            "```\n"
            "GET http://api.nubcoder.com/search?q=python tutorial&max_results=1\n"
            "```\n\n"
            "**2. Multiple results:**\n"
            "```\n"
            "GET http://api.nubcoder.com/search?q=machine learning&max_results=10\n"
            "```\n\n"
            "**3. URL encoded query:**\n"
            "```\n"
            "GET http://api.nubcoder.com/search?q=how%20to%20code&max_results=5\n"
            "```\n\n"
            "**4. Using curl:**\n"
            "```bash\n"
            "curl \"http://api.nubcoder.com/search?q=javascript tutorial&max_results=3\"\n"
            "```\n\n"
            "**5. Browser URL:**\n"
            "```\n"
            "http://api.nubcoder.com/search?q=react js&max_results=20\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Search", callback_data="api_search")]
            ])
        )

    elif data == "api_search_python":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🐍 **Search - Python Implementation**\n\n"
            "```python\n"
            "import requests\n"
            "from typing import List, Dict, Optional\n\n"
            "BASE = 'http://api.nubcoder.com'\n\n"
            "def search_videos(query: str, max_results: int = 5) -> Optional[List[Dict]]:\n"
            "    \"\"\"Search for YouTube videos (free endpoint)\"\"\"\n"
            "    params = {\n"
            "        'q': query,\n"
            "        'max_results': min(max_results, 20)  # API limit\n"
            "    }\n"
            "    \n"
            "    try:\n"
            "        response = requests.get(f'{BASE}/search', params=params, timeout=15)\n"
            "        response.raise_for_status()\n"
            "        \n"
            "        data = response.json()\n"
            "        \n"
            "        if 'error' in data:\n"
            "            print(f\"Search Error: {data['error']}\")\n"
            "            return None\n"
            "        \n"
            "        return data.get('results', [])\n"
            "        \n"
            "    except requests.exceptions.RequestException as e:\n"
            "        print(f\"Search request failed: {e}\")\n"
            "        return None\n\n"
            "def display_search_results(results: List[Dict]):\n"
            "    \"\"\"Format and display search results\"\"\"\n"
            "    if not results:\n"
            "        print(\"No results found\")\n"
            "        return\n"
            "    \n"
            "    print(f\"Found {len(results)} videos:\\n\")\n"
            "    \n"
            "    for i, video in enumerate(results, 1):\n"
            "        title = video.get('title', 'N/A')\n"
            "        channel = video.get('channel_name', 'N/A')\n"
            "        duration = video.get('duration')\n"
            "        views = video.get('views')\n"
            "        video_id = video.get('video_id', '')\n"
            "        \n"
            "        print(f\"{i}. {title}\")\n"
            "        print(f\"   Channel: {channel}\")\n"
            "        \n"
            "        if duration:\n"
            "            mins, secs = divmod(duration, 60)\n"
            "            print(f\"   Duration: {mins}:{secs:02d}\")\n"
            "        \n"
            "        if views:\n"
            "            print(f\"   Views: {views:,}\")\n"
            "        \n"
            "        print(f\"   URL: https://youtube.com/watch?v={video_id}\\n\")\n\n"
            "# Usage examples:\n"
            "# Basic search\n"
            "results = search_videos('python programming', max_results=3)\n"
            "display_search_results(results)\n\n"
            "# Advanced search with filtering\n"
            "def search_and_filter(query: str, min_duration: int = 0):\n"
            "    results = search_videos(query, max_results=10)\n"
            "    if not results:\n"
            "        return []\n"
            "    \n"
            "    # Filter by minimum duration\n"
            "    filtered = [v for v in results if v.get('duration', 0) >= min_duration]\n"
            "    return filtered\n\n"
            "# Find videos longer than 5 minutes\n"
            "long_videos = search_and_filter('machine learning', min_duration=300)\n"
            "display_search_results(long_videos)\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Search", callback_data="api_search")]
            ])
        )


    elif data == "api_ratelimit":
        await callback_query.answer()
        await callback_query.edit_message_text(
            "📊 **Rate Limit Status Endpoint**\n\n"
            "**Endpoint:** `http://api.nubcoder.com/rate-limit-status`\n"
            "**Method:** `GET`\n"
            "**Auth:** Token required\n\n"
            "**Parameters:**\n"
            "• `token` - Your API token\n\n"
            "Select example type:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌐 GET Examples", callback_data="api_ratelimit_get"),
                    InlineKeyboardButton("🐍 Python Implementation", callback_data="api_ratelimit_python")
                ],
                [InlineKeyboardButton("🔙 Back to API Docs", callback_data="api_docs")]
            ])
        )

    elif data == "api_ratelimit_get":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🌐 **Rate Limit - GET Examples**\n\n"
            "**1. Check your quota:**\n"
            "```\n"
            f"GET http://api.nubcoder.com/rate-limit-status?token={user_token}\n"
            "```\n\n"
            "**2. Using curl:**\n"
            "```bash\n"
            f"curl \"http://api.nubcoder.com/rate-limit-status?token={user_token}\"\n"
            "```\n\n"
            "**3. With formatted output:**\n"
            "```bash\n"
            f"curl -s \"http://api.nubcoder.com/rate-limit-status?token={user_token}\" | jq .\n"
            "```\n\n"
            "**4. Browser URL:**\n"
            "```\n"
            f"http://api.nubcoder.com/rate-limit-status?token={user_token}\n"
            "```\n\n"
            "**Example Response:**\n"
            "```json\n"
            "{\n"
            "  \"user_id\": 123456,\n"
            "  \"daily_limit\": 1000,\n"
            "  \"requests_used\": 50,\n"
            "  \"requests_remaining\": 950,\n"
            "  \"reset_time\": \"Midnight UTC\",\n"
            "  \"is_admin\": false,\n"
            "  \"auth_method\": \"token\"\n"
            "}\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Rate Limit", callback_data="api_ratelimit")]
            ])
        )

    elif data == "api_ratelimit_python":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🐍 **Python Examples**\n\n"
            "```python\n"
            "import requests\n\n"
            f"TOKEN = '{user_token}'\n"
            "BASE = 'http://api.nubcoder.com'\n\n"
            "# Search (free)\n"
            "r = requests.get(f'{BASE}/search', \n"
            "    params={'q': 'python tutorial', 'max_results': 5})\n"
            "results = r.json()['results']\n\n"
            "# Get info\n" 
            "r = requests.get(f'{BASE}/info',\n"
            "    params={'token': TOKEN, 'q': 'VIDEO_URL'})\n"
            "data = r.json()\n\n"

            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Rate Limit", callback_data="api_ratelimit")]
            ])
        )

    elif data == "api_health":
        await callback_query.answer()
        await callback_query.edit_message_text(
            "❤️ **Health Check Endpoint**\n\n"
            "**Endpoint:** `http://api.nubcoder.com/health`\n"
            "**Method:** `GET`\n"
            "**Auth:** No token required\n"
            "**Rate Limit:** None\n\n"
            "Select example type:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌐 GET Examples", callback_data="api_health_get"),
                    InlineKeyboardButton("🐍 Python Implementation", callback_data="api_health_python")
                ],
                [InlineKeyboardButton("🔙 Back to API Docs", callback_data="api_docs")]
            ])
        )

    elif data == "api_health_get":
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🌐 **GET Health Check Examples**\n\n"
            "**1. Simple health check:**\n"
            "```\n"
            "GET http://api.nubcoder.com/health\n"
            "```\n\n"
            "**2. Using curl:**\n"
            "```bash\n"
            "curl http://api.nubcoder.com/health\n"
            "```\n\n"
            "**3. With timing information:**\n"
            "```bash\n"
            "curl -w \"Response time: %{time_total}s\\n\" http://api.nubcoder.com/health\n"
            "```\n\n"
            "**4. Test connectivity:**\n"
            "```bash\n"
            "curl -f -s http://api.nubcoder.com/health && echo \"API is healthy\" || echo \"API is down\"\n"
            "```\n\n"
            "**5. Browser URL:**\n"
            "```\n"
            "http://api.nubcoder.com/health\n"
            "```\n\n"
            "**Example Response:**\n"
            "```json\n"
            "{\n"
            "  \"status\": \"ok\"\n"
            "}\n"
            "```\n\n"
            "**Expected Response Time:** < 100ms",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Health Check", callback_data="api_health")]
            ])
        )

    elif data == "api_health_python":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🐍 **Python Examples**\n\n"
            "```python\n"
            "import requests\n\n"
            f"TOKEN = '{user_token}'\n"
            "BASE = 'http://api.nubcoder.com'\n\n"
            "# Search (free)\n"
            "r = requests.get(f'{BASE}/search', \n"
            "    params={'q': 'python tutorial', 'max_results': 5})\n"
            "results = r.json()['results']\n\n"
            "# Get info\n" 
            "r = requests.get(f'{BASE}/info',\n"
            "    params={'token': TOKEN, 'q': 'VIDEO_URL'})\n"
            "data = r.json()\n\n"

            "```",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Health Check", callback_data="api_health")]
            ])
        )

    elif data == "impl_python_part2":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🐍 **Python Implementation - Part 2**\n\n"
            "```python\n"
            "    def search_videos(self, query: str, max_results: int = 5) -> List[Dict]:\n"
            "        \"\"\"Search for videos (free endpoint)\"\"\"\n"
            "        params = {\n"
            "            'q': query,\n"
            "            'max_results': min(max_results, 20)  # API limit\n"
            "        }\n"
            "        result = self._make_request('/search', params)\n"
            "        return result.get('results', [])\n\n"
            "    def get_video_info(self, url_or_query: str, max_results: int = 1) -> Dict:\n"
            "        \"\"\"Get detailed video information\"\"\"\n"
            "        params = {\n"
            "            'token': self.token,\n"
            "            'q': url_or_query,\n"
            "            'max_results': max_results\n"
            "        }\n"
            "        return self._make_request('/info', params)\n\n"
            "    def check_rate_limit(self) -> Dict:\n"
            "        \"\"\"Check current rate limit status\"\"\"\n"
            "        params = {'token': self.token}\n"
            "        return self._make_request('/rate-limit-status', params)\n\n"
            "    def health_check(self) -> Dict:\n"
            "        \"\"\"Check API health status\"\"\"\n"
            "        return self._make_request('/health', {})\n\n"
            "    def download_video(self, video_url: str, output_path: str = None):\n"
            "        \"\"\"Download video using stream URL\"\"\"\n"
            "        info = self.get_video_info(video_url)\n"
            "        stream_url = info.get('url')\n"
            "        \n"
            "        if not stream_url:\n"
            "            raise Exception('No stream URL found')\n"
            "        \n"
            "        filename = output_path or f\"{info.get('title', 'video')}.mp4\"\n"
            "        \n"
            "        with self.session.get(stream_url, stream=True) as r:\n"
            "            r.raise_for_status()\n"
            "            with open(filename, 'wb') as f:\n"
            "                for chunk in r.iter_content(chunk_size=8192):\n"
            "                    f.write(chunk)\n"
            "        return filename\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📄 Part 1", callback_data="impl_python_all"),
                    InlineKeyboardButton("💡 Examples", callback_data="impl_python_examples")
                ],
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation")]
            ])
        )

    elif data == "impl_python_examples":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🐍 **Python Usage Examples**\n\n"
            "```python\n"
            "# Initialize the client\n"
            f"client = YTDLPAPIClient('{user_token}')\n\n"
            "# Example 1: Search for videos\n"
            "try:\n"
            "    videos = client.search_videos('python tutorial', max_results=5)\n"
            "    for video in videos:\n"
            "        print(f\"Title: {video['title']}\")\n"
            "        print(f\"Channel: {video['channel_name']}\")\n"
            "        print(f\"URL: {video['youtube_link']}\")\n"
            "        print('-' * 50)\n"
            "except Exception as e:\n"
            "    print(f\"Search failed: {e}\")\n\n"
            "# Example 2: Get video info by URL\n"
            "try:\n"
            "    url = 'https://youtube.com/watch?v=dQw4w9WgXcQ'\n"
            "    info = client.get_video_info(url)\n"
            "    \n"
            "    print(f\"Title: {info['title']}\")\n"
            "    print(f\"Duration: {info['duration']} seconds\")\n"
            "    print(f\"Views: {info['views']:,}\")\n"
            "    print(f\"Channel: {info['channel_name']}\")\n"
            "    print(f\"Stream URL: {info['url']}\")\n"
            "    print(f\"Thumbnail: {info['thumbnail']}\")\n\n"
            "# Example 3: Check rate limit\n"
            "try:\n"
            "    status = client.check_rate_limit()\n"
            "    used = status['requests_used']\n"
            "    limit = status['daily_limit']\n"
            "    remaining = status['requests_remaining']\n"
            "    \n"
            "    print(f\"Rate limit: {used}/{limit} ({remaining} remaining)\")\n"
            "    \n"
            "    if remaining < 10:\n"
            "        print(\"⚠️ Warning: Low on requests!\")\n"
            "except Exception as e:\n"
            "    print(f\"Rate limit check failed: {e}\")\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Advanced Examples", callback_data="impl_python_advanced"),
                    InlineKeyboardButton("🔧 Error Handling", callback_data="impl_python_errors")
                ],
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation")]
            ])
        )

    elif data == "impl_python_advanced":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🐍 **Advanced Python Examples**\n\n"
            "```python\n"
            "# Example 4: Batch processing with rate limiting\n"
            "import time\n"
            "from typing import List\n\n"
            "def process_multiple_videos(client, urls: List[str]):\n"
            "    results = []\n"
            "    \n"
            "    for i, url in enumerate(urls):\n"
            "        try:\n"
            "            # Check rate limit before each request\n"
            "            status = client.check_rate_limit()\n"
            "            if status['requests_remaining'] < 1:\n"
            "                print(\"Rate limit reached, stopping...\")\n"
            "                break\n"
            "            \n"
            "            print(f\"Processing {i+1}/{len(urls)}: {url}\")\n"
            "            info = client.get_video_info(url)\n"
            "            results.append(info)\n"
            "            \n"
            "            # Be nice to the API - small delay\n"
            "            time.sleep(0.5)\n"
            "            \n"
            "        except Exception as e:\n"
            "            print(f\"Failed to process {url}: {e}\")\n"
            "            continue\n"
            "    \n"
            "    return results\n\n"
            "# Example 5: Smart search with fallback\n"
            "def smart_search(client, query: str):\n"
            "    # First try free search\n"
            "    try:\n"
            "        search_results = client.search_videos(query, max_results=10)\n"
            "        if search_results:\n"
            "            print(f\"Found {len(search_results)} videos:\")\n"
            "            return search_results\n"
            "    except:\n"
            "        pass\n"
            "    \n"
            "    # Fallback to direct search via info endpoint\n"
            "    try:\n"
            "        info_result = client.get_video_info(query, max_results=5)\n"
            "        if 'results' in info_result:\n"
            "            return info_result['results']\n"
            "        else:\n"
            "            return [info_result]  # Single video result\n"
            "    except Exception as e:\n"
            "        print(f\"Search failed completely: {e}\")\n"
            "        return []\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💡 Basic Examples", callback_data="impl_python_examples"),
                    InlineKeyboardButton("🔧 Error Handling", callback_data="impl_python_errors")
                ],
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation")]
            ])
        )

    elif data == "impl_python_errors":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        await callback_query.edit_message_text(
            "🐍 **Error Handling & Best Practices**\n\n"
            "```python\n"
            "# Example 6: Comprehensive error handling\n"
            "def safe_video_info(client, url_or_query: str):\n"
            "    max_retries = 3\n"
            "    retry_delay = 2\n"
            "    \n"
            "    for attempt in range(max_retries):\n"
            "        try:\n"
            "            # Check if we have requests left\n"
            "            status = client.check_rate_limit()\n"
            "            if status['requests_remaining'] < 1:\n"
            "                return {\n"
            "                    'error': 'Rate limit exceeded',\n"
            "                    'reset_time': status['reset_time']\n"
            "                }\n"
            "            \n"
            "            # Attempt to get video info\n"
            "            result = client.get_video_info(url_or_query)\n"
            "            \n"
            "            # Validate result\n"
            "            if not result.get('url'):\n"
            "                return {'error': 'No stream URL available'}\n"
            "            \n"
            "            return {\n"
            "                'success': True,\n"
            "                'data': result,\n"
            "                'attempts': attempt + 1\n"
            "            }\n"
            "            \n"
            "        except Exception as e:\n"
            "            error_msg = str(e).lower()\n"
            "            \n"
            "            if 'rate limit' in error_msg:\n"
            "                return {'error': 'Rate limit exceeded'}\n"
            "            elif 'invalid token' in error_msg:\n"
            "                return {'error': 'Invalid or expired token'}\n"
            "            elif 'timeout' in error_msg:\n"
            "                if attempt < max_retries - 1:\n"
            "                    print(f\"Timeout on attempt {attempt + 1}, retrying...\")\n"
            "                    time.sleep(retry_delay)\n"
            "                    continue\n"
            "                return {'error': 'Request timeout after retries'}\n"
            "            else:\n"
            "                return {'error': f'Unexpected error: {e}'}\n"
            "    \n"
            "    return {'error': 'Max retries exceeded'}\n\n"
            "# Usage example:\n"
            f"client = YTDLPAPIClient('{user_token}')\n"
            "result = safe_video_info(client, 'https://youtube.com/watch?v=dQw4w9WgXcQ')\n\n"
            "if result.get('success'):\n"
            "    print(f\"✅ Success: {result['data']['title']}\")\n"
            "else:\n"
            "    print(f\"❌ Error: {result['error']}\")\n"
            "```",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💡 Basic Examples", callback_data="impl_python_examples"),
                    InlineKeyboardButton("🔄 Advanced Examples", callback_data="impl_python_advanced")
                ],
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation")]
            ])
        )


    elif data == "back_menu":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔧 API Implementation", callback_data="api_implementation"),
                InlineKeyboardButton("📊 Usage Status", callback_data="usage_status")
            ],
            [
                InlineKeyboardButton("🔄 Revoke Token", callback_data="revoke_token"),
                InlineKeyboardButton("❓ Help", callback_data="help")
            ],
            [
                InlineKeyboardButton("📖 API Docs", callback_data="api_docs")
            ]
        ])

        await callback_query.answer()
        await callback_query.edit_message_text(
            "🤖 **YT-DLP API Bot Menu**\n\n"
            "Choose an option below:",
            reply_markup=keyboard
        )

    elif data == "admin_refresh_stats":
        if not is_admin(user_id):
            await callback_query.answer("❌ Admin only.", show_alert=True)
            return

        await callback_query.answer("🔄 Refreshing stats...")
        try:
            from plugins.admin import _build_stats
            _, msg2 = await _build_stats(client)

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_refresh_stats")],
            ])
            await callback_query.edit_message_text(msg2, reply_markup=keyboard)
        except Exception as e:
            await callback_query.edit_message_text(f"❌ Refresh failed: {str(e)}")
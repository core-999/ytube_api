import html
import asyncio
import time
from pyrogram import filters, enums
from pyrogram.client import Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputRichMessage
from pyrogram.enums import ButtonStyle

# Import from tools module
from tools import (
    redis_client, generate_token, is_admin, get_user_token, 
    set_user_token, revoke_user_token, get_user_request_count,
    set_user_request_count, increment_user_requests,
    mask_token, is_group_chat, get_user_token_display,
    send_smart_rich_message
)
from config import BASE_URL

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


def api_url(path: str = "") -> str:
    return f"{BASE_URL}/{path.lstrip('/')}" if path else BASE_URL


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔧 API Implementation", callback_data="api_implementation", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton("📊 Usage Status", callback_data="usage_status", style=ButtonStyle.PRIMARY)
        ],
        [
            InlineKeyboardButton("🔄 Revoke Token", callback_data="revoke_token", style=ButtonStyle.DANGER),
            InlineKeyboardButton("❓ Help", callback_data="help", style=ButtonStyle.DEFAULT)
        ],
        [
            InlineKeyboardButton("📖 API Docs", callback_data="api_docs", style=ButtonStyle.PRIMARY)
        ]
    ])


@Client.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    if not message.from_user:
        return

    user_id = message.from_user.id
    raw_username = message.from_user.username or message.from_user.first_name or "User"
    username = html.escape(raw_username)
    is_grp = is_group_chat(message)
    receiver_uid = user_id if is_grp else None

    # Check if user already has a token
    existing_token = await get_user_token(user_id)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔧 API Implementation", callback_data="api_implementation", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton("📊 Usage Status", callback_data="usage_status", style=ButtonStyle.PRIMARY)
        ],
        [
            InlineKeyboardButton("🔄 Revoke Token", callback_data="revoke_token", style=ButtonStyle.DANGER),
            InlineKeyboardButton("❓ Help", callback_data="help", style=ButtonStyle.DEFAULT)
        ]
    ])

    if existing_token:
        disp_token_private = existing_token
        disp_token_masked = mask_token(existing_token)

        content_html_ephemeral = f"""<h1>Welcome back, {username}!</h1>
<blockquote>Your YT-DLP API integration is active and ready for requests.</blockquote>

<table border="1">
  <tr><th>Setting</th><th>Value</th></tr>
  <tr><td><b>API Token</b></td><td><code>{disp_token_private}</code></td></tr>
  <tr><td><b>Base URL</b></td><td><code>{api_url()}</code></td></tr>
  <tr><td><b>Daily Limit</b></td><td>1,000 requests</td></tr>
  <tr><td><b>Search API</b></td><td>Free &amp; Unlimited</td></tr>
</table>

<details>
  <summary>Quick Start Example</summary>
  <p>Add your token as a query parameter or Authorization header:</p>
  <code>{api_url('info')}?token={disp_token_private}&amp;q=VIDEO_URL</code>
</details>""" + (
            "<blockquote>🔒 <b>Ephemeral Message:</b> This message and your API token are only visible to you in this group.</blockquote>"
            if is_grp else ""
        )

        content_html_fallback = f"""<h1>Welcome back, {username}!</h1>
<blockquote>Your YT-DLP API integration is active and ready for requests.</blockquote>

<table border="1">
  <tr><th>Setting</th><th>Value</th></tr>
  <tr><td><b>API Token</b></td><td><code>{disp_token_masked}</code></td></tr>
  <tr><td><b>Base URL</b></td><td><code>{api_url()}</code></td></tr>
  <tr><td><b>Daily Limit</b></td><td>1,000 requests</td></tr>
  <tr><td><b>Search API</b></td><td>Free &amp; Unlimited</td></tr>
</table>

<details>
  <summary>Quick Start Example</summary>
  <p>Add your token as a query parameter or Authorization header:</p>
  <code>{api_url('info')}?token={disp_token_masked}&amp;q=VIDEO_URL</code>
</details>
<details>
  <summary>🔒 Group Chat Privacy Notice</summary>
  <blockquote>Token is masked for group security. DM the bot /start or promote bot to admin for private ephemeral responses.</blockquote>
</details>"""

        await send_smart_rich_message(
            client=client,
            chat_id=message.chat.id,
            receiver_user_id=receiver_uid,
            rich_message=InputRichMessage(html=content_html_ephemeral),
            fallback_rich_message=InputRichMessage(html=content_html_fallback),
            reply_markup=keyboard
        )
    else:
        # Generate new token
        new_token = generate_token()
        await set_user_token(user_id, new_token)
        disp_token_private = new_token
        disp_token_masked = mask_token(new_token)

        content_html_ephemeral = f"""<h1>Welcome to YT-DLP API, {username}!</h1>
<blockquote>Your personal API key has been provisioned below.</blockquote>

<table border="1">
  <tr><th>Configuration</th><th>Detail</th></tr>
  <tr><td><b>API Token</b></td><td><code>{disp_token_private}</code></td></tr>
  <tr><td><b>Base URL</b></td><td><code>{api_url()}</code></td></tr>
  <tr><td><b>Daily Quota</b></td><td>1,000 requests/day</td></tr>
  <tr><td><b>Search Mode</b></td><td>Free &amp; Unlimited</td></tr>
</table>

<details>
  <summary>How to Use</summary>
  <p>Include your token in requests:</p>
  <code>{api_url('info')}?token={disp_token_private}&amp;q=VIDEO_URL</code>
</details>""" + (
            "<blockquote>🔒 <b>Ephemeral Message:</b> This message and your API token are only visible to you in this group.</blockquote>"
            if is_grp else ""
        )

        content_html_fallback = f"""<h1>Welcome to YT-DLP API, {username}!</h1>
<blockquote>Your personal API key has been provisioned below.</blockquote>

<table border="1">
  <tr><th>Configuration</th><th>Detail</th></tr>
  <tr><td><b>API Token</b></td><td><code>{disp_token_masked}</code></td></tr>
  <tr><td><b>Base URL</b></td><td><code>{api_url()}</code></td></tr>
  <tr><td><b>Daily Quota</b></td><td>1,000 requests/day</td></tr>
  <tr><td><b>Search Mode</b></td><td>Free &amp; Unlimited</td></tr>
</table>

<details>
  <summary>How to Use</summary>
  <p>Include your token in requests:</p>
  <code>{api_url('info')}?token={disp_token_masked}&amp;q=VIDEO_URL</code>
</details>
<details>
  <summary>🔒 Group Chat Privacy Notice</summary>
  <blockquote>Token is masked for group security. DM the bot /start or promote bot to admin for private ephemeral responses.</blockquote>
</details>"""

        await send_smart_rich_message(
            client=client,
            chat_id=message.chat.id,
            receiver_user_id=receiver_uid,
            rich_message=InputRichMessage(html=content_html_ephemeral),
            fallback_rich_message=InputRichMessage(html=content_html_fallback),
            reply_markup=keyboard
        )


@Client.on_message(filters.command("menu"))
async def menu_command(client: Client, message: Message):
    is_grp = is_group_chat(message)
    receiver_uid = message.from_user.id if (message.from_user and is_grp) else None

    content_html = f"""<h1>YT-DLP API Bot Menu</h1>
<blockquote>Choose an option below to manage your token, inspect usage metrics, or view endpoint documentation.</blockquote>

<table border="1">
  <tr><th>Feature</th><th>Description</th></tr>
  <tr><td><b>Implementation</b></td><td>Code examples (cURL, Python, GET)</td></tr>
  <tr><td><b>Usage Status</b></td><td>Live quota tracking &amp; reset timers</td></tr>
  <tr><td><b>Documentation</b></td><td>Endpoint parameters &amp; responses</td></tr>
</table>"""

    content_html_ephemeral = content_html + ("<blockquote>🔒 <b>Ephemeral Message:</b> Only visible to you in this group.</blockquote>" if is_grp else "")

    await send_smart_rich_message(
        client=client,
        chat_id=message.chat.id,
        receiver_user_id=receiver_uid,
        rich_message=InputRichMessage(html=content_html_ephemeral),
        fallback_rich_message=InputRichMessage(html=content_html),
        reply_markup=build_main_menu_keyboard()
    )


@Client.on_message(filters.command("ping"))
async def ping_command(client: Client, message: Message):
    """Measure and display bot latency and uptime using streaming draft and rich message."""
    start = time.time()
    chat_id = message.chat.id
    draft_id = client.rnd_id()
    is_grp = is_group_chat(message)
    receiver_uid = message.from_user.id if (message.from_user and is_grp) else None

    try:
        await client.send_rich_message_draft(
            chat_id=chat_id,
            draft_id=draft_id,
            rich_message=InputRichMessage(html="<b>🏓 Measuring round-trip latency...</b>")
        )
    except Exception:
        pass

    elapsed = round((time.time() - start) * 1000, 2)
    uptime = get_readable_time(int(time.time() - BOT_START_TIME))

    content_html = f"""<h1>🏓 Pong!</h1>
<blockquote>Bot engine and API interfaces are healthy.</blockquote>

<table border="1">
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td><b>⚡ Latency</b></td><td><code>{elapsed} ms</code></td></tr>
  <tr><td><b>⏱ Uptime</b></td><td><code>{uptime}</code></td></tr>
  <tr><td><b>🌐 API Status</b></td><td><b>Online</b></td></tr>
</table>"""

    await send_smart_rich_message(
        client=client,
        chat_id=chat_id,
        receiver_user_id=receiver_uid,
        rich_message=InputRichMessage(html=content_html)
    )


@Client.on_callback_query()
async def handle_callbacks(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    is_grp = is_group_chat(callback_query)

    if data == "view_token":
        token = await get_user_token(user_id)
        if not token:
            await callback_query.answer("❌ No token found. Use /start to get one.", show_alert=True)
        else:
            if is_grp:
                chat_id = callback_query.message.chat.id if callback_query.message else user_id
                try:
                    await client.send_rich_message(
                        chat_id=chat_id,
                        receiver_user_id=user_id,
                        rich_message=InputRichMessage(html=f"""<h1>Your API Token</h1>
<blockquote>🔒 <b>Ephemeral:</b> Only visible to you in this group.</blockquote>
<table border="1">
  <tr><th>Bearer Token</th></tr>
  <tr><td><code>{token}</code></td></tr>
</table>""")
                    )
                    await callback_query.answer("🔑 Token sent ephemerally!", show_alert=False)
                except Exception:
                    # Fallback when bot is not admin in group: send private popup alert
                    await callback_query.answer(f"🔑 Your API Token: {token}", show_alert=True)
            else:
                await callback_query.answer(f"🔑 Your API Token: {token}", show_alert=True)

    elif data == "get_token":
        token = await get_user_token(user_id)
        if not token:
            token = generate_token()
            await set_user_token(user_id, token)
        if is_grp:
            chat_id = callback_query.message.chat.id if callback_query.message else user_id
            try:
                await client.send_rich_message(
                    chat_id=chat_id,
                    receiver_user_id=user_id,
                    rich_message=InputRichMessage(html=f"""<h1>Your API Token</h1>
<blockquote>🔒 <b>Ephemeral:</b> Only visible to you in this group.</blockquote>
<table border="1">
  <tr><th>Bearer Token</th></tr>
  <tr><td><code>{token}</code></td></tr>
</table>""")
                )
                await callback_query.answer("🔑 Token generated ephemerally!", show_alert=False)
            except Exception:
                # Fallback when bot is not admin in group: send private popup alert
                await callback_query.answer(f"🔑 Your API Token: {token}", show_alert=True)
        else:
            await callback_query.answer(f"🔑 Your API Token: {token}", show_alert=True)

    elif data == "api_implementation":
        token = await get_user_token(user_id)
        if token:
            disp_token = token
            await callback_query.answer()
            content_html = f"""<h1>API Implementation Guide</h1>
<blockquote>Select an integration guide or reference below to get started.</blockquote>

<table border="1">
  <tr><th>Field</th><th>Value</th></tr>
  <tr><td><b>Your Token</b></td><td><code>{disp_token}</code></td></tr>
  <tr><td><b>Base URL</b></td><td><code>{api_url()}</code></td></tr>
</table>

<details>
  <summary>Authentication Tips</summary>
  <p>Tokens can be passed as query parameter (<code>?token=...</code>) or Bearer header (<code>Authorization: Bearer ...</code>).</p>
</details>"""

            await callback_query.edit_message_text(
                rich_message=InputRichMessage(html=content_html),
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🌐 GET Examples", callback_data="impl_get_all", style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton("🐍 Python Implement", callback_data="impl_python_all", style=ButtonStyle.PRIMARY)
                    ],
                    [
                        InlineKeyboardButton("📋 Quick Reference", callback_data="impl_quick_ref", style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu", style=ButtonStyle.DEFAULT)
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
        disp_token = token
        admin_badge = "👑 Admin (10,000 req/day)" if is_admin(user_id) else "👤 Standard (1,000 req/day)"

        progress = min(int((request_count / limit) * 10), 10)
        bar = "🟩" * progress + "⬜" * (10 - progress)

        content_html = f"""<h1>Usage Statistics</h1>
<blockquote>Real-time quota monitoring and rate limit status.</blockquote>

<table border="1">
  <tr><th>Metric</th><th>Status</th></tr>
  <tr><td><b>Token</b></td><td><code>{disp_token}</code></td></tr>
  <tr><td><b>Tier</b></td><td>{admin_badge}</td></tr>
  <tr><td><b>Used Today</b></td><td><b>{request_count:,}</b> / {limit:,}</td></tr>
  <tr><td><b>Remaining</b></td><td><b>{remaining:,}</b></td></tr>
  <tr><td><b>Quota Reset</b></td><td>Midnight UTC</td></tr>
  <tr><td><b>Progress</b></td><td>{bar}</td></tr>
</table>

<details>
  <summary>Rate Limiting Rules</summary>
  <p>• Data endpoints (<code>/info</code>, <code>/stream</code>): {limit:,} req/day<br/>
  • Search &amp; Discovery (<code>/search</code>, <code>/trending</code>): Unlimited</p>
</details>"""

        if is_grp:
            content_html += "<blockquote>🔒 <b>Ephemeral:</b> Only visible to you in this group.</blockquote>"

        await callback_query.answer()
        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="usage_status", style=ButtonStyle.PRIMARY)],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "revoke_token":
        await callback_query.answer()
        content_html = """<h1>Revoke API Token</h1>
<blockquote>⚠️ <b>Are you sure?</b> This action will permanently invalidate your current token and generate a new one immediately.</blockquote>
<p>You will need to update the token in all active scripts and servers.</p>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes, Revoke", callback_data="confirm_revoke", style=ButtonStyle.DANGER),
                    InlineKeyboardButton("❌ Cancel", callback_data="back_menu", style=ButtonStyle.DEFAULT)
                ]
            ])
        )

    elif data == "confirm_revoke":
        # Revoke old token
        await revoke_user_token(user_id)

        # Generate new token
        new_token = generate_token()
        await set_user_token(user_id, new_token)
        disp_token = new_token

        await callback_query.answer("✅ Token revoked successfully!")
        content_html = f"""<h1>Token Revoked Successfully</h1>
<blockquote>Your old token has been destroyed and a fresh token is active.</blockquote>

<table border="1">
  <tr><th>Configuration</th><th>Value</th></tr>
  <tr><td><b>New Token</b></td><td><code>{disp_token}</code></td></tr>
  <tr><td><b>Status</b></td><td><b>Active &amp; Ready</b></td></tr>
</table>

<blockquote>⚠️ <b>Important:</b> Update your API calls with the new token immediately.</blockquote>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "help":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Help &amp; Documentation</h1>
<blockquote>Quick reference guide for bot commands and core API endpoints.</blockquote>

<h2>Bot Commands</h2>
<table border="1">
  <tr><th>Command</th><th>Description</th></tr>
  <tr><td><code>/start</code></td><td>Provision or view your token</td></tr>
  <tr><td><code>/menu</code></td><td>Interactive navigation menu</td></tr>
  <tr><td><code>/status</code></td><td>Check daily quota consumption</td></tr>
  <tr><td><code>/token</code></td><td>View active API bearer token</td></tr>
  <tr><td><code>/revoke</code></td><td>Cycle and revoke credentials</td></tr>
  <tr><td><code>/ping</code></td><td>Inspect latency and uptime</td></tr>
</table>

<h2>API Endpoints</h2>
<table border="1">
  <tr><th>Endpoint</th><th>Auth Required</th><th>Description</th></tr>
  <tr><td><code>/info</code></td><td>Yes</td><td>Video metadata + direct stream URL</td></tr>
  <tr><td><code>/search</code></td><td>No (Free)</td><td>Fast YouTube video search</td></tr>
  <tr><td><code>/rate-limit-status</code></td><td>Yes</td><td>Check remaining quota via API</td></tr>
  <tr><td><code>/health</code></td><td>No</td><td>Service health probe</td></tr>
</table>

<details>
  <summary>Python Quick Example</summary>
  <pre><code class="language-python">import requests
res = requests.get(
    "{api_url('info')}",
    params={{"token": "{user_token}", "q": "VIDEO_URL"}}
)
print(res.json())</code></pre>
</details>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📖 Full API Docs", callback_data="api_docs", style=ButtonStyle.PRIMARY)],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "impl_get_all":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>GET Endpoint Examples</h1>
<blockquote>Ready-to-use HTTP GET requests with your credentials.</blockquote>

<h2>1. Video Info &amp; Stream URL</h2>
<pre><code>GET {api_url('info')}?token={user_token}&amp;q=https://youtube.com/watch?v=dQw4w9WgXcQ</code></pre>

<h2>2. Search Videos (Free)</h2>
<pre><code>GET {api_url('search')}?q=python+tutorial&amp;max_results=5</code></pre>

<h2>3. Rate Limit Quota Check</h2>
<pre><code>GET {api_url('rate-limit-status')}?token={user_token}</code></pre>

<h2>4. Health Probe</h2>
<pre><code>GET {api_url('health')}</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "impl_python_all":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Python Implementation (Part 1)</h1>
<blockquote>Lightweight standalone helper functions using <code>requests</code>.</blockquote>

<pre><code class="language-python">import requests
from typing import List, Dict, Optional, Tuple

API_TOKEN = "{user_token}"
BASE_URL = "{api_url()}"

def get_video_info(url_or_query: str, max_results: int = 1):
    \"\"\"Returns direct stream URL and metadata.\"\"\"
    r = requests.get(
        f"{{BASE_URL}}/info",
        params={{"token": API_TOKEN, "q": url_or_query, "max_results": max_results}},
        timeout=30
    )
    return r.json()

def search_videos(query: str, max_results: int = 5):
    \"\"\"Free search endpoint without stream URLs.\"\"\"
    r = requests.get(
        f"{{BASE_URL}}/search",
        params={{"q": query, "max_results": max_results}},
        timeout=30
    )
    return r.json().get("results", [])</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📄 Part 2: Client Class", callback_data="impl_python_part2", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("💡 Usage Examples", callback_data="impl_python_examples", style=ButtonStyle.PRIMARY)
                ],
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "impl_quick_ref":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Quick Reference Guide</h1>
<blockquote>Essential configuration values and endpoint parameters.</blockquote>

<table border="1">
  <tr><th>Resource</th><th>Target</th></tr>
  <tr><td><b>Token</b></td><td><code>{user_token}</code></td></tr>
  <tr><td><b>Base URL</b></td><td><code>{api_url()}</code></td></tr>
</table>

<h2>Endpoints</h2>
<table border="1">
  <tr><th>Route</th><th>Output</th></tr>
  <tr><td><code>/info</code></td><td>Metadata + direct MP4/Audio stream URL</td></tr>
  <tr><td><code>/search</code></td><td>Video title, ID, duration, channel</td></tr>
  <tr><td><code>/rate-limit-status</code></td><td>Current quota consumption</td></tr>
  <tr><td><code>/health</code></td><td>Service status check</td></tr>
</table>

<details>
  <summary>Python Quick One-Liner</summary>
  <pre><code class="language-python">import requests
data = requests.get("{api_url('info')}?token={user_token}&amp;q=VIDEO_URL").json()</code></pre>
</details>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_docs":
        await callback_query.answer()
        content_html = f"""<h1>API Documentation</h1>
<blockquote>Interactive endpoint reference and schema descriptions.</blockquote>

<table border="1">
  <tr><th>Feature</th><th>Specification</th></tr>
  <tr><td><b>Base URL</b></td><td><code>{api_url()}/</code></td></tr>
  <tr><td><b>Authentication</b></td><td><code>?token=YOUR_TOKEN</code> or Bearer Header</td></tr>
  <tr><td><b>Quota</b></td><td>1,000 calls/day (Data), Unlimited (Search)</td></tr>
</table>

<p>Select an endpoint below to inspect parameters and example payloads:</p>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎥 Video Info", callback_data="api_info", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("🔍 Search", callback_data="api_search", style=ButtonStyle.PRIMARY)
                ],
                [
                    InlineKeyboardButton("📊 Rate Limit", callback_data="api_ratelimit", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("❤️ Health Check", callback_data="api_health", style=ButtonStyle.PRIMARY)
                ],
                [
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu", style=ButtonStyle.DEFAULT)
                ]
            ])
        )

    elif data == "api_info":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Video Info Endpoint</h1>
<blockquote>Extract rich metadata and playable direct CDN stream URLs.</blockquote>

<table border="1">
  <tr><th>Property</th><th>Value</th></tr>
  <tr><td><b>Path</b></td><td><code>{api_url('info')}</code></td></tr>
  <tr><td><b>Method</b></td><td><code>GET</code></td></tr>
  <tr><td><b>Auth</b></td><td>Bearer Token Required</td></tr>
</table>

<h2>Parameters</h2>
<table border="1">
  <tr><th>Param</th><th>Type</th><th>Description</th></tr>
  <tr><td><code>token</code></td><td>string</td><td>Your personal API token</td></tr>
  <tr><td><code>q</code></td><td>string</td><td>YouTube video URL, ID, or query</td></tr>
  <tr><td><code>max_results</code></td><td>int</td><td>Results count when searching (default 1)</td></tr>
</table>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌐 GET Examples", callback_data="api_info_get", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("🐍 Python Code", callback_data="api_info_python", style=ButtonStyle.PRIMARY)
                ],
                [InlineKeyboardButton("🔙 Back to API Docs", callback_data="api_docs", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_info_get":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Video Info — GET Examples</h1>
<blockquote>cURL and browser query formats for <code>/info</code>.</blockquote>

<h2>1. Query by Video URL</h2>
<pre><code>GET {api_url('info')}?token={user_token}&amp;q=https://youtube.com/watch?v=dQw4w9WgXcQ</code></pre>

<h2>2. Query by Search Term</h2>
<pre><code>GET {api_url('info')}?token={user_token}&amp;q=python+tutorial&amp;max_results=1</code></pre>

<h2>3. cURL Command</h2>
<pre><code class="language-bash">curl "{api_url('info')}?token={user_token}&amp;q=https://youtube.com/watch?v=dQw4w9WgXcQ"</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Video Info", callback_data="api_info", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_info_python":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Video Info — Python Code</h1>
<blockquote>Robust client script with error and timeout handling.</blockquote>

<pre><code class="language-python">import requests

TOKEN = "{user_token}"
BASE = "{api_url()}"

def fetch_video(url_or_query: str):
    params = {{"token": TOKEN, "q": url_or_query, "max_results": 1}}
    try:
        r = requests.get(f"{{BASE}}/info", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        print(f"Title: {{data.get('title')}}")
        print(f"Stream URL: {{data.get('url')}}")
        return data
    except Exception as e:
        print(f"Error fetching info: {{e}}")
        return None

# Run fetch
fetch_video("https://youtube.com/watch?v=dQw4w9WgXcQ")</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Video Info", callback_data="api_info", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_search":
        await callback_query.answer()
        content_html = f"""<h1>Search Endpoint (Free)</h1>
<blockquote>Fast video searching with metadata (no quota consumed).</blockquote>

<table border="1">
  <tr><th>Property</th><th>Specification</th></tr>
  <tr><td><b>Path</b></td><td><code>{api_url('search')}</code></td></tr>
  <tr><td><b>Method</b></td><td><code>GET</code></td></tr>
  <tr><td><b>Auth</b></td><td>None (Free &amp; Public)</td></tr>
  <tr><td><b>Output</b></td><td>Metadata list (No stream URLs)</td></tr>
</table>

<h2>Parameters</h2>
<table border="1">
  <tr><th>Param</th><th>Type</th><th>Description</th></tr>
  <tr><td><code>q</code></td><td>string</td><td>Search keywords</td></tr>
  <tr><td><code>max_results</code></td><td>int</td><td>Number of results (1–20)</td></tr>
</table>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌐 GET Examples", callback_data="api_search_get", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("🐍 Python Code", callback_data="api_search_python", style=ButtonStyle.PRIMARY)
                ],
                [InlineKeyboardButton("🔙 Back to API Docs", callback_data="api_docs", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_search_get":
        await callback_query.answer()
        content_html = f"""<h1>Search — GET Examples</h1>
<blockquote>Public search request patterns.</blockquote>

<h2>1. Basic Single Result</h2>
<pre><code>GET {api_url('search')}?q=python+tutorial&amp;max_results=1</code></pre>

<h2>2. Multi-Result Batch (10 items)</h2>
<pre><code>GET {api_url('search')}?q=machine+learning&amp;max_results=10</code></pre>

<h2>3. cURL</h2>
<pre><code class="language-bash">curl "{api_url('search')}?q=javascript+tutorial&amp;max_results=3"</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Search", callback_data="api_search", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_search_python":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Search — Python Implementation</h1>
<blockquote>Search and parse YouTube video results.</blockquote>

<pre><code class="language-python">import requests
from typing import List, Dict

BASE = "{api_url()}"

def search_youtube(query: str, max_results: int = 5) -> List[Dict]:
    params = {{"q": query, "max_results": min(max_results, 20)}}
    r = requests.get(f"{{BASE}}/search", params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("results", [])

results = search_youtube("python async programming", 3)
for v in results:
    print(f"• {{v['title']}} ({{v.get('channel_name')}})")
    print(f"  URL: https://youtube.com/watch?v={{v.get('video_id')}}")</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Search", callback_data="api_search", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_ratelimit":
        await callback_query.answer()
        content_html = f"""<h1>Rate Limit Status Endpoint</h1>
<blockquote>Check your real-time quota balance and reset schedule via HTTP.</blockquote>

<table border="1">
  <tr><th>Property</th><th>Value</th></tr>
  <tr><td><b>Path</b></td><td><code>{api_url('rate-limit-status')}</code></td></tr>
  <tr><td><b>Method</b></td><td><code>GET</code></td></tr>
  <tr><td><b>Auth</b></td><td>Bearer Token Required</td></tr>
</table>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌐 GET Examples", callback_data="api_ratelimit_get", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("🐍 Python Code", callback_data="api_ratelimit_python", style=ButtonStyle.PRIMARY)
                ],
                [InlineKeyboardButton("🔙 Back to API Docs", callback_data="api_docs", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_ratelimit_get":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Rate Limit — GET Examples</h1>
<blockquote>Inspect quota responses with cURL.</blockquote>

<h2>Request</h2>
<pre><code>GET {api_url('rate-limit-status')}?token={user_token}</code></pre>

<h2>JSON Response Schema</h2>
<pre><code class="language-json">{{
  "user_id": 123456789,
  "daily_limit": 1000,
  "requests_used": 42,
  "requests_remaining": 958,
  "reset_time": "Midnight UTC",
  "is_admin": false
}}</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Rate Limit", callback_data="api_ratelimit", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_ratelimit_python":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Rate Limit — Python Example</h1>
<blockquote>Check remaining quota before executing heavy batch jobs.</blockquote>

<pre><code class="language-python">import requests

TOKEN = "{user_token}"
BASE = "{api_url()}"

def check_quota():
    r = requests.get(f"{{BASE}}/rate-limit-status", params={{"token": TOKEN}}, timeout=10)
    data = r.json()
    print(f"Used: {{data['requests_used']}} / {{data['daily_limit']}}")
    print(f"Remaining: {{data['requests_remaining']}}")
    return data['requests_remaining'] > 0

if check_quota():
    print("✅ Ready to process video requests")</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Rate Limit", callback_data="api_ratelimit", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_health":
        await callback_query.answer()
        content_html = f"""<h1>Health Check Endpoint</h1>
<blockquote>Automated health probe for monitoring and uptime checkers.</blockquote>

<table border="1">
  <tr><th>Property</th><th>Specification</th></tr>
  <tr><td><b>Path</b></td><td><code>{api_url('health')}</code></td></tr>
  <tr><td><b>Method</b></td><td><code>GET</code></td></tr>
  <tr><td><b>Auth</b></td><td>None</td></tr>
  <tr><td><b>Rate Limit</b></td><td>None</td></tr>
</table>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌐 GET Examples", callback_data="api_health_get", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("🐍 Python Code", callback_data="api_health_python", style=ButtonStyle.PRIMARY)
                ],
                [InlineKeyboardButton("🔙 Back to API Docs", callback_data="api_docs", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_health_get":
        await callback_query.answer()
        content_html = f"""<h1>Health Probe — GET Examples</h1>
<blockquote>Probe API health status and response latency.</blockquote>

<h2>1. Direct GET</h2>
<pre><code>GET {api_url('health')}</code></pre>

<h2>2. cURL with Exit Code Check</h2>
<pre><code class="language-bash">curl -f -s "{api_url('health')}" &amp;&amp; echo "API is Online"</code></pre>

<h2>Response</h2>
<pre><code class="language-json">{{
  "status": "ok"
}}</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Health Check", callback_data="api_health", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "api_health_python":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Health Check — Python Example</h1>
<blockquote>Verify API connectivity with timeout bounds.</blockquote>

<pre><code class="language-python">import requests

def is_api_online():
    try:
        r = requests.get("{api_url('health')}", timeout=5)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except requests.RequestException:
        return False

print("Online:" if is_api_online() else "Offline")</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Health Check", callback_data="api_health", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "impl_python_part2":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Python Implementation (Part 2)</h1>
<blockquote>Production-ready <code>YtubeAPIClient</code> wrapper with connection pooling.</blockquote>

<pre><code class="language-python">import requests
from typing import Dict, List

class YtubeAPIClient:
    def __init__(self, token: str, base_url: str = "{api_url()}"):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def get_info(self, url_or_query: str, max_results: int = 1) -> Dict:
        r = self.session.get(
            f"{{self.base_url}}/info",
            params={{"token": self.token, "q": url_or_query, "max_results": max_results}},
            timeout=30
        )
        r.raise_for_status()
        return r.json()

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        r = self.session.get(
            f"{{self.base_url}}/search",
            params={{"q": query, "max_results": min(max_results, 20)}},
            timeout=15
        )
        r.raise_for_status()
        return r.json().get("results", [])

    def quota(self) -> Dict:
        r = self.session.get(f"{{self.base_url}}/rate-limit-status", params={{"token": self.token}})
        return r.json()</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📄 Part 1", callback_data="impl_python_all", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("💡 Usage Examples", callback_data="impl_python_examples", style=ButtonStyle.PRIMARY)
                ],
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "impl_python_examples":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Python Usage Examples</h1>
<blockquote>Calling client methods for search, info, and quota checks.</blockquote>

<pre><code class="language-python">client = YtubeAPIClient("{user_token}")

# 1. Search videos
videos = client.search("python fast api", max_results=3)
for v in videos:
    print(f"• {{v['title']}} ({{v['channel_name']}})")

# 2. Get direct streaming link
info = client.get_info("https://youtube.com/watch?v=dQw4w9WgXcQ")
print(f"Direct stream URL: {{info.get('url')}}")

# 3. Check remaining quota
status = client.quota()
print(f"Remaining requests today: {{status.get('requests_remaining')}}")</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Advanced Batching", callback_data="impl_python_advanced", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("🔧 Error Handling", callback_data="impl_python_errors", style=ButtonStyle.PRIMARY)
                ],
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "impl_python_advanced":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Advanced Batching &amp; Fallbacks</h1>
<blockquote>Batch extraction with polite delays and automatic retry fallbacks.</blockquote>

<pre><code class="language-python">import time

def process_batch(client: YtubeAPIClient, urls: list[str]):
    results = []
    for i, url in enumerate(urls, 1):
        try:
            status = client.quota()
            if status.get("requests_remaining", 0) &lt; 1:
                print("Daily quota exhausted, stopping batch.")
                break
            info = client.get_info(url)
            results.append(info)
            time.sleep(0.3)  # Polite pacing
        except Exception as e:
            print(f"Failed {{url}}: {{e}}")
    return results</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💡 Basic Examples", callback_data="impl_python_examples", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("🔧 Error Handling", callback_data="impl_python_errors", style=ButtonStyle.PRIMARY)
                ],
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "impl_python_errors":
        user_token = await get_user_token(user_id) or "YOUR_TOKEN"
        await callback_query.answer()
        content_html = f"""<h1>Error Handling &amp; Best Practices</h1>
<blockquote>Handling rate limits, expired tokens, and network retries.</blockquote>

<pre><code class="language-python">import requests
import time

def safe_get_video(client: YtubeAPIClient, url: str, retries: int = 3):
    for attempt in range(retries):
        try:
            return client.get_info(url)
        except requests.HTTPError as e:
            if e.response.status_code == 429:
                print("Rate limit reached. Try again after midnight UTC.")
                return None
            elif e.response.status_code == 401:
                print("Invalid or revoked token. Use /token to check.")
                return None
            time.sleep(1)
        except requests.RequestException:
            time.sleep(1)
    return None</code></pre>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💡 Basic Examples", callback_data="impl_python_examples", style=ButtonStyle.PRIMARY),
                    InlineKeyboardButton("🔄 Advanced Batching", callback_data="impl_python_advanced", style=ButtonStyle.PRIMARY)
                ],
                [InlineKeyboardButton("🔙 Back to Implementation", callback_data="api_implementation", style=ButtonStyle.DEFAULT)]
            ])
        )

    elif data == "back_menu":
        await callback_query.answer()
        content_html = f"""<h1>YT-DLP API Bot Menu</h1>
<blockquote>Choose an option below to manage your token, inspect usage metrics, or view endpoint documentation.</blockquote>

<table border="1">
  <tr><th>Feature</th><th>Description</th></tr>
  <tr><td><b>Implementation</b></td><td>Code examples (cURL, Python, GET)</td></tr>
  <tr><td><b>Usage Status</b></td><td>Live quota tracking &amp; reset timers</td></tr>
  <tr><td><b>Documentation</b></td><td>Endpoint parameters &amp; responses</td></tr>
</table>"""

        await callback_query.edit_message_text(
            rich_message=InputRichMessage(html=content_html),
            reply_markup=build_main_menu_keyboard()
        )

    elif data == "admin_refresh_stats":
        if not is_admin(user_id):
            try:
                await client.send_rich_message(
                    chat_id=callback_query.message.chat.id if callback_query.message else user_id,
                    receiver_user_id=user_id,
                    rich_message=InputRichMessage(html="<blockquote>❌ <b>Access Denied:</b> Admin privileges required.</blockquote>")
                )
            except Exception:
                pass
            await callback_query.answer("❌ Admin only.", show_alert=True)
            return

        await callback_query.answer("🔄 Refreshing statistics...")
        try:
            from plugins.admin import _build_stats
            _, msg2_html = await _build_stats(client)

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_refresh_stats", style=ButtonStyle.PRIMARY)],
            ])
            await callback_query.edit_message_text(
                rich_message=InputRichMessage(html=msg2_html),
                reply_markup=keyboard
            )
        except Exception as e:
            await callback_query.edit_message_text(
                rich_message=InputRichMessage(html=f"<blockquote>❌ <b>Refresh failed:</b> {html.escape(str(e))}</blockquote>")
            )
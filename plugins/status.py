import html
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, InputRichMessage
from pyrogram.enums import ButtonStyle

from tools import get_user_token, get_user_request_count, is_admin, mask_token, is_group_chat, send_smart_rich_message

@Client.on_message(filters.command("status"))
async def status_command(client: Client, message: Message):
    user_id = message.from_user.id
    token = await get_user_token(user_id)
    is_grp = is_group_chat(message)
    receiver_uid = user_id if is_grp else None
    
    if not token:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Get Token", callback_data="get_token", style=ButtonStyle.SUCCESS)]
        ])
        content_html_ephemeral = """<h1>Usage Status</h1>
<blockquote>❌ You don't have an active API token yet. Click below to generate one immediately.</blockquote>"""
        if is_grp:
            content_html_ephemeral += "<blockquote>🔒 <b>Ephemeral:</b> Only visible to you in this group.</blockquote>"

        content_html_fallback = """<h1>Usage Status</h1>
<blockquote>❌ You don't have an active API token yet. Click below to generate one immediately.</blockquote>
<details>
  <summary>🔒 Group Chat Privacy Notice</summary>
  <blockquote>DM the bot /status or promote bot to admin to receive private ephemeral messages.</blockquote>
</details>"""

        await send_smart_rich_message(
            client=client,
            chat_id=message.chat.id,
            receiver_user_id=receiver_uid,
            rich_message=InputRichMessage(html=content_html_ephemeral),
            fallback_rich_message=InputRichMessage(html=content_html_fallback),
            reply_markup=keyboard
        )
        return
    
    request_count = await get_user_request_count(user_id)
    limit = 10000 if is_admin(user_id) else 1000
    remaining = max(0, limit - request_count)
    
    # Progress bar
    progress = min(int((request_count / limit) * 10), 10)
    bar = "🟩" * progress + "⬜" * (10 - progress)

    disp_token_private = token
    disp_token_masked = mask_token(token)
    admin_badge = "👑 Admin (10,000 req/day)" if is_admin(user_id) else "👤 Standard (1,000 req/day)"
    
    content_html_ephemeral = f"""<h1>Usage Status</h1>
<blockquote>Real-time quota monitoring and rate limit tracking.</blockquote>

<table border="1">
  <tr><th>Property</th><th>Value</th></tr>
  <tr><td><b>Token</b></td><td><code>{disp_token_private}</code></td></tr>
  <tr><td><b>Tier</b></td><td>{admin_badge}</td></tr>
  <tr><td><b>Used Today</b></td><td><b>{request_count:,}</b> / {limit:,}</td></tr>
  <tr><td><b>Remaining</b></td><td><b>{remaining:,}</b></td></tr>
  <tr><td><b>Reset Timer</b></td><td>Midnight UTC</td></tr>
  <tr><td><b>Progress</b></td><td>{bar}</td></tr>
</table>"""

    if is_grp:
        content_html_ephemeral += (
            "<blockquote>🔒 <b>Ephemeral Message:</b> This usage status and your API token are only visible to you in this group.</blockquote>"
        )

    content_html_fallback = f"""<h1>Usage Status</h1>
<blockquote>Real-time quota monitoring and rate limit tracking.</blockquote>

<table border="1">
  <tr><th>Property</th><th>Value</th></tr>
  <tr><td><b>Token</b></td><td><code>{disp_token_masked}</code></td></tr>
  <tr><td><b>Tier</b></td><td>{admin_badge}</td></tr>
  <tr><td><b>Used Today</b></td><td><b>{request_count:,}</b> / {limit:,}</td></tr>
  <tr><td><b>Remaining</b></td><td><b>{remaining:,}</b></td></tr>
  <tr><td><b>Reset Timer</b></td><td>Midnight UTC</td></tr>
  <tr><td><b>Progress</b></td><td>{bar}</td></tr>
</table>
<details>
  <summary>🔒 Group Chat Privacy Notice</summary>
  <blockquote>Token is masked for group security. DM the bot /status or promote bot to admin for private ephemeral responses.</blockquote>
</details>"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="usage_status", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton("🔑 View Token", callback_data="view_token", style=ButtonStyle.PRIMARY)
        ],
        [
            InlineKeyboardButton("📱 Main Menu", callback_data="back_menu", style=ButtonStyle.DEFAULT)
        ]
    ])
    
    await send_smart_rich_message(
        client=client,
        chat_id=message.chat.id,
        receiver_user_id=receiver_uid,
        rich_message=InputRichMessage(html=content_html_ephemeral),
        fallback_rich_message=InputRichMessage(html=content_html_fallback),
        reply_markup=keyboard
    )

@Client.on_message(filters.command("token"))
async def token_command(client: Client, message: Message):
    user_id = message.from_user.id
    token = await get_user_token(user_id)
    is_grp = is_group_chat(message)
    receiver_uid = user_id if is_grp else None
    
    if token:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Check Usage", callback_data="usage_status", style=ButtonStyle.PRIMARY),
                InlineKeyboardButton("🔄 Revoke Token", callback_data="revoke_token", style=ButtonStyle.DANGER)
            ],
            [
                InlineKeyboardButton("📱 Main Menu", callback_data="back_menu", style=ButtonStyle.DEFAULT)
            ]
        ])
        
        content_html_ephemeral = f"""<h1>Your API Token</h1>
<blockquote>🔒 <b>Ephemeral Message:</b> This token is only visible to you in this group.</blockquote>

<table border="1">
  <tr><th>Active Bearer Token</th></tr>
  <tr><td><code>{token}</code></td></tr>
</table>""" if is_grp else f"""<h1>Your API Token</h1>
<blockquote>Keep this token secure and pass it in your API requests.</blockquote>

<table border="1">
  <tr><th>Active Bearer Token</th></tr>
  <tr><td><code>{token}</code></td></tr>
</table>"""

        content_html_fallback = f"""<h1>Your API Token</h1>
<details>
  <summary>🔒 Token Masked</summary>
  <blockquote>Token is masked for group security. DM the bot /token to view your full token or promote bot to admin.</blockquote>
</details>

<table border="1">
  <tr><th>Active Bearer Token</th></tr>
  <tr><td><code>{mask_token(token)}</code></td></tr>
</table>"""

        await send_smart_rich_message(
            client=client,
            chat_id=message.chat.id,
            receiver_user_id=receiver_uid,
            rich_message=InputRichMessage(html=content_html_ephemeral),
            fallback_rich_message=InputRichMessage(html=content_html_fallback),
            reply_markup=keyboard
        )
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Get Token", callback_data="get_token", style=ButtonStyle.SUCCESS)]
        ])
        content_html_ephemeral = """<h1>API Token</h1>
<blockquote>❌ You don't have an active token yet. Click below to provision one.</blockquote>"""
        if is_grp:
            content_html_ephemeral += "<blockquote>🔒 <b>Ephemeral:</b> Only visible to you in this group.</blockquote>"

        content_html_fallback = """<h1>API Token</h1>
<blockquote>❌ You don't have an active token yet. Click below to provision one.</blockquote>
<details>
  <summary>🔒 Group Chat Privacy Notice</summary>
  <blockquote>DM the bot /token or promote bot to admin to receive private ephemeral messages.</blockquote>
</details>"""

        await send_smart_rich_message(
            client=client,
            chat_id=message.chat.id,
            receiver_user_id=receiver_uid,
            rich_message=InputRichMessage(html=content_html_ephemeral),
            fallback_rich_message=InputRichMessage(html=content_html_fallback),
            reply_markup=keyboard
        )

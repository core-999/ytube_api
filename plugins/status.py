from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from tools import get_user_token, get_user_request_count, is_admin

@Client.on_message(filters.command("status"))
async def status_command(client: Client, message: Message):
    user_id = message.from_user.id
    token = await get_user_token(user_id)
    
    if not token:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Get Token", callback_data="get_token")]
        ])
        await message.reply_text(
            "❌ You don't have a token yet.\n\n"
            "Click the button below to get started!",
            reply_markup=keyboard
        )
        return
    
    request_count = await get_user_request_count(user_id)
    limit = 10000 if is_admin(user_id) else 1000
    remaining = max(0, limit - request_count)
    
    # Progress bar
    progress = min(int((request_count / limit) * 10), 10)
    bar = "🟩" * progress + "⬜" * (10 - progress)
    
    status_text = (
        f"📊 **Usage Status**\n\n"
        f"🔑 Token: `{token}`\n"
        f"📈 Used: **{request_count}**/{limit}\n"
        f"📉 Remaining: **{remaining}**\n"
        f"🕒 Reset: Midnight UTC\n\n"
        f"📊 Progress: {bar}"
    )
    
    if is_admin(user_id):
        status_text += "\n\n👑 **Admin privileges active**"
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="usage_status"),
            InlineKeyboardButton("🔑 View Token", callback_data="view_token")
        ],
        [
            InlineKeyboardButton("📱 Main Menu", callback_data="back_menu")
        ]
    ])
    
    await message.reply_text(status_text, reply_markup=keyboard)

@Client.on_message(filters.command("token"))
async def token_command(client: Client, message: Message):
    user_id = message.from_user.id
    token = await get_user_token(user_id)
    
    if token:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Check Usage", callback_data="usage_status"),
                InlineKeyboardButton("🔄 Revoke Token", callback_data="revoke_token")
            ],
            [
                InlineKeyboardButton("📱 Main Menu", callback_data="back_menu")
            ]
        ])
        await message.reply_text(
            f"🔑 **Your API Token:**\n\n`{token}`\n\n"
            "Keep this secure and use it in your API calls!",
            reply_markup=keyboard
        )
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Get Token", callback_data="get_token")]
        ])
        await message.reply_text(
            "❌ You don't have a token yet.\n\n"
            "Click the button below to get started!",
            reply_markup=keyboard
        )

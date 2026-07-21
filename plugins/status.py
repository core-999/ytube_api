from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from tools import get_user_token, get_user_request_count, is_admin, mask_token, is_group_chat

@Client.on_message(filters.command("status"))
async def status_command(client: Client, message: Message):
    user_id = message.from_user.id
    token = await get_user_token(user_id)
    is_grp = is_group_chat(message)
    
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

    disp_token = mask_token(token) if is_grp else token
    
    status_text = (
        f"📊 **Usage Status**\n\n"
        f"🔑 Token: `{disp_token}`\n"
        f"📈 Used: **{request_count}**/{limit}\n"
        f"📉 Remaining: **{remaining}**\n"
        f"🕒 Reset: Midnight UTC\n\n"
        f"📊 Progress: {bar}"
    )
    
    if is_admin(user_id):
        status_text += "\n\n👑 **Admin privileges active**"
    
    if is_grp:
        status_text += "\n\n🔒 *Token is masked in group chats for security.*"

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
    is_grp = is_group_chat(message)
    
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
        disp_token = mask_token(token) if is_grp else token
        note = "🔒 *Token is masked in group chats for security. DM the bot to view your full token.*" if is_grp else "Keep this secure and use it in your API calls!"
        await message.reply_text(
            f"🔑 **Your API Token:**\n\n`{disp_token}`\n\n{note}",
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


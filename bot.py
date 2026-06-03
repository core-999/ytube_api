from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, GROUP, CHANNEL

telegram_app = Client(
    "ytdlp_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN, in_memory=True,
    plugins=dict(root="plugins"),
    device_model="Desktop",
    system_version="Windows 10",
    app_version="3.4.3 x64",
    lang_code="en",
    lang_pack="tdesktop"
)

def setup_bot_commands():
    from pyrogram.types import BotCommand
    commands = [
        BotCommand("start", "🚀 Get your API token and welcome message"),
        BotCommand("menu", "📋 Show main menu with options"),
        BotCommand("ping", "🏓 Check bot latency"),
        BotCommand("status", "📊 Check your usage statistics"),
        BotCommand("token", "🔑 View your current API token"),
        BotCommand("revoke", "🔄 Revoke your current token"),
        BotCommand("help", "❓ Get help and API documentation"),
    ]
    try:
        telegram_app.set_bot_commands(commands)
        print("✅ Bot commands set successfully")
    except Exception as e:
        print(f"⚠️ Failed to set bot commands: {e}")

def run_bot():
    telegram_app.start()
    setup_bot_commands()
    telegram_app.run()
    telegram_app.stop()

if __name__ == "__main__":
    run_bot()

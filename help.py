from telegram import Update
from telegram.ext import ContextTypes
from comm_checker import check_user_approval
from config import ADMIN_CHAT_ID

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.effective_user.id
        if not await check_user_approval(user_id):
            await update.message.reply_text("❌ You are not approved to use this command.")
            return

        # Initialize help text with available commands
        help_text = (
            "/start - Start the bot\n"
            "/subnet <ip> <mask> - Calculate subnet\n"
            "/help - Show this help message\n"
            "/status - Show bot status\n"
            "/sysinfo - Show system information\n"
            "/speedtest - Show the speed of the bot's hosted server\n"
            "/ping - Show response time from the hosted server\n"
            "/music <song_name> - Play music\n"
            "/video <video_name> - Play video\n"
            "/bgremove - Remove background of an image\n"
            "/ai - Chat with AI\n"
            "/store <text> - Save a note (or reply to a message to save its text)\n"
            "/get <id or keyword> - Retrieve a note by ID or keyword\n"
            "/listnotes - List all your notes\n"
            "/delnote <id> - Delete a note by ID\n"
        )

        await update.message.reply_text(help_text)
    except Exception as e:
        print(f"Error in help command: {e}")
        await update.message.reply_text("❌ An error occurred while fetching the help message.")
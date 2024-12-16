from telegram import Update
from telegram.ext import ContextTypes

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if not await check_user_approval(update.effective_user.id):
            await update.message.reply_text("You are not approved to use this command.")
            return

        if not command_states['music']:
            await update.message.reply_text("The music command is currently disabled.")
            return          
        help_text = (
            "/start - Start the bot\n"
            "/subnet <ip> <mask> - Calculate subnet\n"
            "/help - Show this help message\n"
            "/status - Show bot status\n"
            "/sysinfo - Show system information\n"
            "/speedtest - to show the speed of the bot hosted server\n"
            "/ping - to show the respons time from the hosted server\n"
            "/music - to listen music\n"
            "/video - to view video\n"
        )
        await update.message.reply_text(help_text)
    except Exception as e:
        print(f"Error in help command: {e}")

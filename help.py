from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler

HELP_TOPICS = {
    "start": "Starts the bot and greets the user.",
    "subnet": "Usage: `/subnet <ip> <mask>`\nCalculates the subnet info.",
    "help": "Shows this help message with interactive buttons.",
    "status": "Shows the bot's health and uptime.",
    "sysinfo": "Displays system information (CPU, memory, disk, etc).",
    "speedtest": "Runs a speedtest on the bot's server.",
    "ping": "Measures response time from the bot's host.",
    "music": "Usage: `/music <name>`\nStreams music with the given name.",
    "video": "Usage: `/video <name>`\nStreams video with the given name.",
    "bgremove": "Removes background from uploaded photo.",
    "ai": "Chat with the AI. Use `/ai <your prompt>`.",
    "listcommands": "Lists all available commands and their status.",
}

def get_resized_keyboard(commands_per_row=2):
    buttons = []
    row = []
    for i, cmd in enumerate(HELP_TOPICS.keys(), 1):
        row.append(InlineKeyboardButton(f"/{cmd}", callback_data=f"help_{cmd}"))
        if i % commands_per_row == 0:
            buttons.append(row)
            row = []
    if row:  # append any leftover buttons
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        bot_username = (await context.bot.get_me()).username
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📬 Click here for help", url=f"https://t.me/{bot_username}?start=help")]
        ])
        await update.message.reply_text("Click below to get help in private 👇", reply_markup=keyboard)
        return

    await update.message.reply_text(
        "📚 *Available Commands*\nSelect a command to view detailed help:",
        reply_markup=get_resized_keyboard(commands_per_row=2),
        parse_mode="Markdown"
    )

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    command = query.data.replace("help_", "")
    description = HELP_TOPICS.get(command, "No help available for this command.")

    await query.edit_message_text(
        text=f"*Help for /{command}:*\n\n{description}",
        parse_mode="Markdown"
    )

def register_help_handlers(application):
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="^help_"))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler

HELP_TOPICS = {
    "note_usage": {
    "description": "🗒️ Usage and help for saving, retrieving, and deleting notes.",
    "category": "main",
    "subcommands": {
        "keep": "📝 Usage: `/keep \"note content\" notename` or reply with `/keep notename`\nSaves a note in group/private chat.",
        "notes": "📋 Usage: `/notes`\nDisplays a list of saved notes in the chat.",
        "#notename": "📖 Usage: `#notename`\nRetrieves the note with the given name.",
        "delete": "🗑️ Usage: `/delete notename`\nDeletes a saved note. Group deletion requires admin privileges."
        }
    },
    "general": {
        "description": "📚 General commands for interacting with the bot.",
        "category": "main",
        "subcommands": {
            "start": "🚀 Starts the bot and greets the user.",
            "help": "📚 Shows this help menu with interactive buttons.",
            "listcommands": "📜 Lists all available commands and their status."
        }
    },
    "system": {
        "description": "🛠️ Utilities for system information and diagnostics.",
        "category": "main",
        "subcommands": {
            "status": "🩺 Shows the bot's health and uptime.",
            "sysinfo": "💻 Displays system information (CPU, memory, disk, etc.).",
            "speedtest": "⚡ Runs a speed test on the bot's server.",
            "ping": "🏓 Measures response time from the bot's host.",
            "subnet": "🌐 Usage: `/subnet <ip> <mask>`\nCalculates subnet information."
        }
    },
    "media": {
        "description": "🎥 Commands for handling media content.",
        "category": "main",
        "subcommands": {
            "music": "🎵 Usage: `/music <name>`\nStreams music with the given name.",
            "video": "🎥 Usage: `/video <name>`\nStreams video with the given name.",
            "bgremove": "🖼️ Removes the background from an uploaded photo."
        }
    },
    "ai": {
        "description": "🤖 Commands for AI interactions.",
        "category": "main",
        "subcommands": {
            "ai": "🤖 Usage: `/ai <prompt>`\nChat with the AI."
        }
    },
    "group_manager": {
        "description": "👥 Manage your Telegram group with these commands (admin only).",
        "category": "main",
        "subcommands": {
            "welcome": "📩 Usage: `/welcome [message|off]`\nSets a welcome message. use {mention} to mention user on joining.",
            "goodbye": "👋 Usage: `/goodbye [message|off]`\nSets a goodbye message. use {mention} to mention user on left.",
            "filter": "🔍 Usage: `/filter <keyword> <reply>`\nAdd a keyword filter with a custom reply.",
            "stop": "🛑 Usage: `/stop <keyword>`\nRemove a keyword filter.",
            "mute": "🔇 Usage: `/mute`\nMute a user (reply to their message).",
            "tmute": "⏳ Usage: `/tmute <time>`\nTemporarily mute a user (e.g., 1h, 2d). Reply to their message.",
            "unmute": "🔊 Usage: `/unmute`\nUnmute a user (reply to their message).",
            "kick": "👢 Usage: `/kick`\nKick a user from the group (reply to their message).",
            "ban": "🚫 Usage: `/ban`\nBan a user from the group (reply to their message).",
            "tban": "⏳ Usage: `/tban <time>`\nTemporarily ban a user (e.g., 1h, 2d). Reply to their message.",
            "unban": "✅ Usage: `/unban <user_id>`\nUnban a user by their ID.",
            "warn": "⚠️ Usage: `/warn [reason]`\nWarn a user (reply to their message).",
            "warns": "ℹ️ Usage: `/warns`\nCheck a user's warning count (reply to their message).",
            "warnlimit": "🔢 Usage: `/warnlimit <number>`\nSet the warning limit for the group.",
            "warnmode": "⚙️ Usage: `/warnmode <mute|kick|ban>`\nSet the action for reaching the warning limit.",
            "lock": "🔒 Usage: `/lock` or `/lock <type|all> Lock specific chat features. Use without arguments to get interactive buttons.",
            "unlock": "🔓 Usage: `/unlock` or `/unlock <type|all>` Unlock specific chat features. Use without arguments to get interactive buttons.",
            "pin": "📌 Usage: `/pin [loud]`\nPin a message (reply or with text). Use 'loud' to notify members.",
            "action": "⚙️ Usage: `/action`\nToggle auto-deletion of service messages (join/left).",
            "tagadmin": "📣 Usage: `/tagadmin [message]` Mention all administrators in the group.",
            "promote": "⬆️ Usage: `/promote [title]`\nPromote a user to admin with a custom title (reply to their message).",
            "permission": "⚙️ Usage: `/permission` Grant a specific permission to an admin. Reply to their message and use without arguments to get interactive buttons.",
            "revokeperm": "❌ Usage: `/revokeperm` Revoke a specific permission from an admin. Reply to their message and use without arguments to get interactive buttons.",
            "demote": "⬇️ Usage: `/demote`\nDemote an admin (reply to their message)."
        }
    }
}


def get_resized_keyboard(commands, commands_per_row=3):
    buttons = []
    row = []
    for i, cmd in enumerate(commands, 1):
        row.append(InlineKeyboardButton(f"/{cmd}", callback_data=f"help_{cmd}"))
        if i % commands_per_row == 0:
            buttons.append(row)
            row = []
    if row:  # Append any leftover buttons
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

async def help_command(update: Update, context: ContextTypes):
    if update.effective_chat.type != "private":
        bot_username = (await context.bot.get_me()).username
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📬 Get Help in Private", url=f"https://t.me/{bot_username}?start=help")]
        ])
        await update.message.reply_text(
            "Click below to view the help menu in a private chat 👇",
            reply_markup=keyboard
        )
        return

    await update.message.reply_text(
        "📚 *Bot Command Categories*\n\nSelect a category below to view its commands:",
        reply_markup=get_resized_keyboard([cmd for cmd, data in HELP_TOPICS.items() if data["category"] == "main"], commands_per_row=3),
        parse_mode="Markdown"
    )

async def help_callback(update: Update, context: ContextTypes):
    query = update.callback_query
    await query.answer()

    command = query.data.replace("help_", "")

    if command == "main":
        # Show the main categories menu
        await query.edit_message_text(
            text="📚 *Bot Command Categories*\n\nSelect a category below to view its commands:",
            reply_markup=get_resized_keyboard([cmd for cmd, data in HELP_TOPICS.items() if data["category"] == "main"], commands_per_row=3),
            parse_mode="Markdown"
        )
        return

    if command in HELP_TOPICS and "subcommands" in HELP_TOPICS[command]:
        # Show submenu for category commands
        subcommands = HELP_TOPICS[command].get("subcommands", {})
        keyboard = get_resized_keyboard(subcommands.keys(), commands_per_row=3)
        # Convert inline_keyboard to list, append back button, and create new InlineKeyboardMarkup
        keyboard_list = list(keyboard.inline_keyboard)
        keyboard_list.append([InlineKeyboardButton("⬅️ Back to Categories", callback_data="help_main")])
        keyboard = InlineKeyboardMarkup(keyboard_list)
        await query.edit_message_text(
            text=f"{HELP_TOPICS[command]['description']}\n\nSelect a command to view its details:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # Check if the command is a subcommand
    for category, data in HELP_TOPICS.items():
        if "subcommands" in data and command in data["subcommands"]:
            description = data["subcommands"][command]
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"⬅️ Back to {category.title()} Commands", callback_data=f"help_{category}")]
            ])
            await query.edit_message_text(
                text=f"*Help for /{command}:*\n\n{description}",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return

    # Handle invalid commands
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Categories", callback_data="help_main")]
    ])
    await query.edit_message_text(
        text="❌ No help available for this command.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

def register_help_handlers(application):
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="^help_"))
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from command_template import CommandSpec, guard_command


HELP_TOPICS = {
    "note_usage": {
        "description": "📝 Save, list, recall, and delete notes with simple shortcuts.",
        "category": "main",
        "subcommands": {
            "keep": "<b>Usage</b>\n<code>/keep \"note content\" notename</code>\nOr reply with <code>/keep notename</code> to save the replied message.",
            "notes": "<b>Usage</b>\n<code>/notes</code>\nShows the saved notes available in this chat.",
            "#notename": "<b>Usage</b>\n<code>#notename</code>\nFetches the saved note with that name.",
            "delete": "<b>Usage</b>\n<code>/delete notename</code>\nDeletes a saved note. Group note deletion requires admin rights.",
        },
    },
    "general": {
        "description": "✨ Core bot commands and quick navigation.",
        "category": "main",
        "subcommands": {
            "start": "Starts the bot and shows the welcome message.",
            "help": "Shows this interactive help menu.",
            "listcommands": "Lists toggleable commands and their current status.",
        },
    },
    "system": {
        "description": "🛠️ Health checks, diagnostics, and server information.",
        "category": "main",
        "subcommands": {
            "status": "Shows bot uptime and basic health information.",
            "sysinfo": "Displays CPU, memory, disk, and system details.",
            "speedtest": "Runs a network speed test on the host.",
            "ping": "Checks reachability for a hostname from the bot server.",
            "subnet": "<b>Usage</b>\n<code>/subnet &lt;ip&gt; &lt;mask&gt;</code> or <code>/subnet &lt;ip/cidr&gt;</code>",
        },
    },
    "media": {
        "description": "🎵 Download and process media with guided commands.",
        "category": "main",
        "subcommands": {
            "music": "<b>Usage</b>\n<code>/music &lt;song name&gt;</code>\nSearches and sends the audio result.",
            "video": "<b>Usage</b>\n<code>/video &lt;video name&gt;</code>\nSearches and sends the video result.",
            "bgremove": "Reply to a photo with <code>/bgremove</code> to remove the background.",
            "mirror": "<b>Usage</b>\n<code>/mirror</code>\nDownloads locally, uploads to the configured target, and returns a shareable link.",
            "cancel": "<b>Usage</b>\n<code>/cancel [task_id]</code>\nCancels an active mirror task.",
        },
    },
    "ai": {
        "description": "🤖 Ask questions, analyze files, and chat with Gemini.",
        "category": "main",
        "subcommands": {
            "ai": "<b>Usage</b>\n<code>/ai &lt;prompt&gt;</code>\nYou can also reply to a file or image with <code>/ai</code>.",
        },
    },
    "group_manager": {
        "description": "👥 Group moderation, automation, filters, locks, and admin tools.",
        "category": "main",
        "subcommands": {
            "welcome": "<b>Usage</b>\n<code>/welcome [message|off]</code>",
            "goodbye": "<b>Usage</b>\n<code>/goodbye [message|off]</code>",
            "filter": "<b>Usage</b>\n<code>/filter &lt;keyword&gt; &lt;reply&gt;</code>",
            "stop": "<b>Usage</b>\n<code>/stop &lt;keyword&gt;</code>",
            "mute": "<b>Usage</b>\n<code>/mute</code> by reply.",
            "tmute": "<b>Usage</b>\n<code>/tmute &lt;time&gt;</code> such as <code>30m</code> or <code>2h</code>.",
            "unmute": "<b>Usage</b>\n<code>/unmute</code> by reply.",
            "kick": "<b>Usage</b>\n<code>/kick</code> by reply.",
            "ban": "<b>Usage</b>\n<code>/ban</code> by reply.",
            "tban": "<b>Usage</b>\n<code>/tban &lt;time&gt;</code> such as <code>1h</code> or <code>2d</code>.",
            "unban": "<b>Usage</b>\n<code>/unban &lt;user_id&gt;</code>",
            "warn": "<b>Usage</b>\n<code>/warn [reason]</code>",
            "warns": "<b>Usage</b>\n<code>/warns</code>",
            "warnlimit": "<b>Usage</b>\n<code>/warnlimit &lt;number&gt;</code>",
            "warnmode": "<b>Usage</b>\n<code>/warnmode &lt;mute|kick|ban&gt;</code>",
            "locks": "<b>Usage</b>\n<code>/locks</code>\nOpens the interactive chat lock manager.",
            "pin": "<b>Usage</b>\n<code>/pin [loud]</code>",
            "action": "<b>Usage</b>\n<code>/action</code>",
            "tagadmin": "<b>Usage</b>\n<code>/tagadmin [message]</code>",
            "promote": "<b>Usage</b>\n<code>/promote [title]</code>",
            "permissions": "<b>Usage</b>\n<code>/permissions</code>",
            "demote": "<b>Usage</b>\n<code>/demote</code>",
        },
    },
}


def get_resized_keyboard(commands, commands_per_row=3):
    buttons = []
    row = []
    for i, cmd in enumerate(commands, 1):
        row.append(InlineKeyboardButton(f"/{cmd}", callback_data=f"help_{cmd}"))
        if i % commands_per_row == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_command(
        update,
        CommandSpec(name="help", requires_approval=False, disabled_message="⚠️ Help is currently disabled."),
    ):
        return

    if update.effective_chat.type != "private":
        bot_username = (await context.bot.get_me()).username
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Open Help in Private", url=f"https://t.me/{bot_username}?start=help")]]
        )
        await update.message.reply_text(
            "<b>Private Help Menu</b>\nTap below to open the full help menu in a private chat.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(
        "<b>Bot Command Categories</b>\nChoose a category below to explore its commands.",
        reply_markup=get_resized_keyboard(
            [cmd for cmd, data in HELP_TOPICS.items() if data["category"] == "main"],
            commands_per_row=3,
        ),
        parse_mode="HTML",
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    command = query.data.replace("help_", "")

    if command == "main":
        await query.edit_message_text(
            text="<b>Bot Command Categories</b>\nChoose a category below to explore its commands.",
            reply_markup=get_resized_keyboard(
                [cmd for cmd, data in HELP_TOPICS.items() if data["category"] == "main"],
                commands_per_row=3,
            ),
            parse_mode="HTML",
        )
        return

    if command in HELP_TOPICS and "subcommands" in HELP_TOPICS[command]:
        subcommands = HELP_TOPICS[command].get("subcommands", {})
        keyboard = get_resized_keyboard(subcommands.keys(), commands_per_row=3)
        keyboard_list = list(keyboard.inline_keyboard)
        keyboard_list.append([InlineKeyboardButton("Back to Categories", callback_data="help_main")])
        await query.edit_message_text(
            text=f"<b>{HELP_TOPICS[command]['description']}</b>\nChoose a command to view its details.",
            reply_markup=InlineKeyboardMarkup(keyboard_list),
            parse_mode="HTML",
        )
        return

    for category, data in HELP_TOPICS.items():
        if "subcommands" in data and command in data["subcommands"]:
            description = data["subcommands"][command]
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"Back to {category.title()} Commands", callback_data=f"help_{category}")]]
            )
            await query.edit_message_text(
                text=f"<b>Help for /{command}</b>\n\n{description}",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Back to Categories", callback_data="help_main")]])
    await query.edit_message_text(
        text="<b>No Help Available</b>\nI couldn't find a help entry for that command.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


def register_help_handlers(application):
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="^help_"))

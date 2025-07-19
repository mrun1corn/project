import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from hello import bot_start, jaan
from subcal import subnet
from help import register_help_handlers
from systemstatus import bot_status, system_status, speedtest, ping, reboot
from comm_checker import enable_command, disable_command, approve_user, revoke_user, list_commands_status
from player import play_audio, play_video
from config import BOT_TOKEN, ADMIN_CHAT_ID
from shell import register_shell_handlers
from bg_remove import remove_bg
from gemini import ai_command
from reel import handle_video_link, VIDEO_URL_REGEX
from sticker import kang
from group_management import register_group_management
from notes import register_note_handlers

async def post_init(application):
    try:
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text="🤖 Bot has started and is now online."
        )
    except Exception as e:
        print(f"Failed to send startup message to admin: {e}")

def main() -> None:
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .connection_pool_size(20)
        .build()
    )

    # Register notes handlers first to ensure high priority for #notename messages
    register_note_handlers(application)

    # Register command handlers
    application.add_handler(CommandHandler("start", bot_start))
    application.add_handler(CommandHandler("jaan", jaan))
    application.add_handler(CommandHandler("subnet", subnet))
    application.add_handler(CommandHandler("status", bot_status))
    application.add_handler(CommandHandler("sysinfo", system_status))
    application.add_handler(CommandHandler("speedtest", speedtest))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("reboot", reboot))
    application.add_handler(CommandHandler("music", play_audio))
    application.add_handler(CommandHandler("video", play_video))
    application.add_handler(CommandHandler("enable", enable_command))
    application.add_handler(CommandHandler("disable", disable_command))
    application.add_handler(CommandHandler("approve", approve_user))
    application.add_handler(CommandHandler("revoke", revoke_user))
    application.add_handler(CommandHandler("bgremove", remove_bg))
    application.add_handler(CommandHandler("ai", ai_command))
    application.add_handler(CommandHandler("kang", kang))
    application.add_handler(CommandHandler("listcommands", list_commands_status))

    # Register help command (with buttons and callbacks)
    register_help_handlers(application)

    # Register video/reel link handler
    application.add_handler(MessageHandler(filters.Regex(VIDEO_URL_REGEX) & ~filters.COMMAND, handle_video_link))

    # Register shell command handlers
    register_shell_handlers(application)

    # Register group management handlers
    register_group_management(application)

    # Bot startup message
    application.post_init = post_init

    print("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
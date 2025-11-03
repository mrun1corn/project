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
from comm_checker import enable_command, disable_command, approve_user, revoke_user, list_commands_status, enforce_user_access
from player import play_audio, play_video
from settings import settings
from shell import register_shell_handlers
from bg_remove import remove_bg
from gemini import ai_command
from reel import handle_video_link, VIDEO_URL_REGEX
from sticker import kang
from mirror import mirror_command
from group_management import register_group_management
from notes import register_note_handlers

async def post_init(application):
    try:
        await application.bot.send_message(
            chat_id=settings.admin_chat_id,
            text="🤖 Bot has started and is now online."
        )
    except Exception as e:
        print(f"Failed to send startup message to admin: {e}")

def main() -> None:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not configured. Set it in your environment or .env file.")
    if not settings.admin_chat_id:
        print("⚠️  ADMIN_CHAT_ID is not configured. Admin notifications and approvals may not work as expected.")

    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .concurrent_updates(True)
        .connection_pool_size(20)
        .build()
    )

    # Register notes handlers first to ensure high priority for #notename messages
    register_note_handlers(application)

    # Global access guard (blocks unapproved users before other handlers run)
    application.add_handler(MessageHandler(filters.ALL, enforce_user_access), group=-100)

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
    application.add_handler(CommandHandler("mirror", mirror_command))
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

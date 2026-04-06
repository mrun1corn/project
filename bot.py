from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from pymongo.errors import PyMongoError

from bg_remove import remove_bg
from comm_checker import (
    approve_user,
    disable_command,
    enable_command,
    enforce_user_access,
    list_commands_status,
    revoke_user,
)
from database import get_collection
from gemini import ai_command
from group_management import register_group_management
from hello import bot_start, jaan
from help import register_help_handlers
from mirror import register_mirror_handlers
from notes import register_note_handlers
from player import play_audio, play_video
from reel import VIDEO_URL_REGEX, handle_video_link
from settings import settings
from shell import register_shell_handlers
from sticker import kang
from subcal import subnet
from systemstatus import bot_status, ping, reboot, speedtest, system_status


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    print(f"Unhandled error: {error}")

    message = None
    if isinstance(update, Update):
        message = update.effective_message

    if message is None:
        return

    if isinstance(error, PyMongoError):
        await message.reply_text(
            "<b>Database Warning</b>\nThe configuration database is currently unavailable. Some commands may fall back to default behavior until the connection is restored.",
            parse_mode="HTML",
        )
        return

    await message.reply_text(
        "<b>Something Went Wrong</b>\n⚠️ I hit an unexpected error while processing your request.",
        parse_mode="HTML",
    )


async def post_init(application):
    try:
        await application.bot.send_message(
            chat_id=settings.admin_chat_id,
            text="<b>Bot Online</b>\n✅ Startup completed and polling is now active.",
            parse_mode="HTML",
        )
    except Exception as exc:
        print(f"Failed to send startup message to admin: {exc}")

    try:
        await get_collection("bot_config").database.command("ping")
        print("MongoDB connection check passed.")
    except Exception as exc:
        print(f"MongoDB preflight check failed: {exc}")
        if settings.admin_chat_id:
            try:
                await application.bot.send_message(
                    chat_id=settings.admin_chat_id,
                    text=(
                        "<b>MongoDB Warning</b>\n"
                        "⚠️ Preflight failed. The bot will use in-memory defaults until the database is reachable.\n\n"
                        f"<code>{exc}</code>"
                    ),
                    parse_mode="HTML",
                )
            except Exception as notify_exc:
                print(f"Failed to send MongoDB warning to admin: {notify_exc}")


def main() -> None:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not configured. Set it in your environment or .env file.")
    if not settings.admin_chat_id:
        print("ADMIN_CHAT_ID is not configured. Admin notifications and approvals may not work as expected.")

    application = ApplicationBuilder().token(settings.bot_token).concurrent_updates(True).connection_pool_size(20).build()

    register_note_handlers(application)
    application.add_error_handler(global_error_handler)

    application.add_handler(MessageHandler(filters.COMMAND, enforce_user_access), group=-100)
    application.add_handler(CallbackQueryHandler(enforce_user_access), group=-100)

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
    register_mirror_handlers(application)
    application.add_handler(CommandHandler("listcommands", list_commands_status))

    register_help_handlers(application)
    application.add_handler(MessageHandler(filters.Regex(VIDEO_URL_REGEX) & ~filters.COMMAND, handle_video_link))
    register_shell_handlers(application)
    register_group_management(application)

    application.post_init = post_init

    print("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()

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

from src.core.config import settings
from src.core.database import get_collection
from src.core.security import (
    approve_user,
    disable_command,
    enable_command,
    enforce_user_access,
    list_commands_status,
    revoke_user,
)
from src.modules import (
    ai,
    bgremove,
    group,
    help,
    mirror,
    notes,
    player,
    shell,
    start,
    sticker,
    system,
)

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    print(f"Unhandled error: {error}")

    message = None
    if isinstance(update, Update):
        message = update.effective_message

    if message is None:
        return

    if isinstance(error, PyMongoError):
        # Database issues are handled by transparent local JSON fallback.
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
                        "⚠️ Preflight failed. The bot will use local JSON fallback files until the database is reachable.\n\n"
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

    application.add_error_handler(global_error_handler)

    # Core Security Middleware
    application.add_handler(MessageHandler(filters.COMMAND, enforce_user_access), group=-100)
    application.add_handler(CallbackQueryHandler(enforce_user_access), group=-100)

    # Core Access Management Commands
    application.add_handler(CommandHandler("enable", enable_command))
    application.add_handler(CommandHandler("disable", disable_command))
    application.add_handler(CommandHandler("approve", approve_user))
    application.add_handler(CommandHandler("revoke", revoke_user))
    application.add_handler(CommandHandler("listcommands", list_commands_status))

    # Register Feature Modules
    start.register(application)
    system.register(application)
    player.register(application)
    bgremove.register(application)
    ai.register(application)
    sticker.register(application)
    mirror.register(application)
    help.register(application)
    shell.register(application)
    group.register(application)
    notes.register(application)

    application.post_init = post_init

    print("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()

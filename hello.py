from telegram import Update
from telegram.ext import ContextTypes


async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "<b>Welcome</b>\n"
                "✨ I'm online and ready to help.\n"
                "Use <code>/help</code> to explore everything I can do."
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        print(f"Error in bot_start: {exc}")


async def jaan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="<b>Jaan Mode</b>\n💬 Say babe.",
            parse_mode="HTML",
        )
    except Exception as exc:
        print(f"Error in jaan: {exc}")

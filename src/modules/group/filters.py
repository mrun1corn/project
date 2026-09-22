from telegram import Update
from telegram.ext import ContextTypes

from .constants import USAGE_FILTER_MSG, USAGE_STOP_MSG
from .permissions import (
    admin_only,
    error_handler,
    group_management_command_enabled_check,
)
from .state import load_group, save_group


@admin_only
@group_management_command_enabled_check("filter")
@error_handler
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(USAGE_FILTER_MSG)
        return
    group = await load_group(chat_id)
    trigger = context.args[0].lower()
    reply = " ".join(context.args[1:])
    group['filters'][trigger] = reply
    await save_group(chat_id, group)
    await update.message.reply_text(f"Filter added for '{trigger}'")


@admin_only
@group_management_command_enabled_check("stop")
@error_handler
async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(USAGE_STOP_MSG)
        return
    trigger = context.args[0].lower()
    group = await load_group(chat_id)
    if trigger in group['filters']:
        del group['filters'][trigger]
        await save_group(chat_id, group)
        await update.message.reply_text(f"Filter '{trigger}' removed")
    else:
        await update.message.reply_text("Filter not found.")


@error_handler
async def filter_responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    group = await load_group(chat_id)
    for trigger, reply in group.get("filters", {}).items():
        if trigger in text:
            await update.message.reply_text(reply)
            break

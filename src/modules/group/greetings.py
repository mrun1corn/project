import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from .constants import ADMIN_PERMISSION_MSG
from .permissions import (
    admin_only,
    error_handler,
    get_bot_admin_rights,
    group_management_command_enabled_check,
    is_user_admin,
)
from .state import load_group, save_group


def _format_member_message(msg: str, member, chat_title: str) -> str:
    """Formats a message with member and chat details."""
    return msg.format(
        first=escape_markdown(member.first_name or "", version=2),
        fullname=escape_markdown(member.full_name, version=2),
        username=escape_markdown(f"@{member.username}" if member.username else "", version=2),
        mention=member.mention_markdown_v2(),
        chatname=escape_markdown(chat_title or "", version=2)
    )


@admin_only
@group_management_command_enabled_check("welcome")
@error_handler
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)

    if not context.args:
        await update.message.reply_text(f"Welcome message:\n{group['welcome'] or 'Disabled'}")
        return

    arg = " ".join(context.args)
    if arg.lower() in ['off', 'no']:
        group['welcome'] = None
        await update.message.reply_text("Welcome message disabled.")
    else:
        group['welcome'] = arg
        await update.message.reply_text(f"Welcome message set to:\n{arg}")

    await save_group(chat_id, group)


@admin_only
@group_management_command_enabled_check("goodbye")
@error_handler
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)

    if not context.args:
        await update.message.reply_text(f"Goodbye message:\n{group['goodbye'] or 'Disabled'}")
        return

    arg = " ".join(context.args)
    if arg.lower() in ['off', 'no']:
        group['goodbye'] = None
        await update.message.reply_text("Goodbye message disabled.")
    else:
        group['goodbye'] = arg
        await update.message.reply_text(f"Goodbye message set to:\n{arg}")

    await save_group(chat_id, group)


@error_handler
async def mention_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await is_user_admin(context, query.message.chat.id, query.from_user.id):
        await query.edit_message_text(ADMIN_PERMISSION_MSG)
        return

    chat_id = query.message.chat.id
    group = await load_group(chat_id)

    _, type_, choice = query.data.split('_')

    mention_enabled = choice == 'yes'
    group[f'{type_}_mention'] = mention_enabled
    await save_group(chat_id, group)

    await query.edit_message_text(f"User mentions for {type_} message have been {'enabled' if mention_enabled else 'disabled'}.")


@error_handler
async def member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)

    msg = group.get("welcome")
    if not msg:
        return

    mention_enabled = group.get('welcome_mention', True)

    for m in update.message.new_chat_members:
        formatted_text = _format_member_message(msg, m, update.effective_chat.title)
        if not mention_enabled:
            formatted_text = formatted_text.replace(m.mention_markdown_v2(), escape_markdown(m.full_name, version=2))
        await context.bot.send_message(chat_id=chat_id, text=formatted_text, parse_mode=ParseMode.MARKDOWN_V2)


@error_handler
async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)

    msg = group.get("goodbye")
    if not msg:
        return

    mention_enabled = group.get('goodbye_mention', True)
    m = update.message.left_chat_member

    formatted_text = _format_member_message(msg, m, update.effective_chat.title)
    if not mention_enabled:
        formatted_text = formatted_text.replace(m.mention_markdown_v2(), escape_markdown(m.full_name, version=2))
    await context.bot.send_message(chat_id=chat_id, text=formatted_text, parse_mode=ParseMode.MARKDOWN_V2)


@error_handler
async def service_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)

    if not group.get('action_delete', True) or not update.effective_message:
        return

    bot_rights = await get_bot_admin_rights(context, chat_id)
    if not bot_rights.can_delete_messages:
        return

    try:
        await asyncio.sleep(0.5)
        await update.effective_message.delete()
    except Exception as e:
        print(f"Could not delete service message in chat {chat_id}: {e}")

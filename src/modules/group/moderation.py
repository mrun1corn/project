import time
from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from .constants import (
    INVALID_TIME_FORMAT_MSG,
    NO_ADMIN_BAN_MSG,
    NO_ADMIN_KICK_MSG,
    NO_ADMIN_MUTE_BAN_MSG,
    NO_ADMIN_TBAN_MSG,
    NO_ADMIN_WARN_MSG,
    REPLY_TO_USER_MSG,
    USAGE_PURGE_MSG,
    USAGE_UNBAN_MSG,
    USAGE_WARN_LIMIT_MSG,
    USAGE_WARN_MODE_MSG,
)
from .permissions import (
    admin_only,
    bot_has_permissions,
    error_handler,
    group_management_command_enabled_check,
    is_user_admin,
)
from .state import load_group, save_group


def parse_time(time_str: str) -> int:
    """Converts a time string like '1d', '2h', '30m' to seconds."""
    if not time_str:
        return 0
    try:
        unit = time_str[-1].lower()
        value = int(time_str[:-1])
        if unit == 'm':
            return value * 60
        elif unit == 'h':
            return value * 3600
        elif unit == 'd':
            return value * 86400
    except (ValueError, IndexError):
        pass
    return 0


@admin_only
@group_management_command_enabled_check("mute")
@bot_has_permissions(["can_restrict_members"])
@error_handler
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_MUTE_BAN_MSG)
        return

    await context.bot.restrict_chat_member(
        chat_id,
        target_user_id,
        permissions=ChatPermissions(can_send_messages=False)
    )
    await update.message.reply_text("User muted.")


@admin_only
@group_management_command_enabled_check("tmute")
@bot_has_permissions(["can_restrict_members"])
@error_handler
async def tmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_MUTE_BAN_MSG)
        return

    duration_str = context.args[0] if context.args else "1h"
    duration_sec = parse_time(duration_str)
    if duration_sec == 0:
        await update.message.reply_text(INVALID_TIME_FORMAT_MSG)
        return

    until_date = time.time() + duration_sec
    await context.bot.restrict_chat_member(
        chat_id,
        target_user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=int(until_date)
    )
    await update.message.reply_text(f"User muted for {duration_str}.")


@admin_only
@group_management_command_enabled_check("unmute")
@bot_has_permissions(["can_restrict_members"])
@error_handler
async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_audios=True,
            can_send_voice_notes=True,
            can_send_documents=True,
            can_send_video_notes=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
    )
    await update.message.reply_text("User unmuted.")


@admin_only
@group_management_command_enabled_check("kick")
@bot_has_permissions(["can_restrict_members"])
@error_handler
async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_KICK_MSG)
        return

    await context.bot.ban_chat_member(chat_id, target_user_id)
    await context.bot.unban_chat_member(chat_id, target_user_id)
    await update.message.reply_text("User kicked.")


@admin_only
@group_management_command_enabled_check("ban")
@bot_has_permissions(["can_restrict_members"])
@error_handler
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_BAN_MSG)
        return

    await context.bot.ban_chat_member(chat_id, target_user_id)
    await update.message.reply_text("User banned.")


@admin_only
@group_management_command_enabled_check("tban")
@bot_has_permissions(["can_restrict_members"])
@error_handler
async def tban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_TBAN_MSG)
        return

    duration_str = context.args[0] if context.args else "1d"
    duration_sec = parse_time(duration_str)
    if duration_sec == 0:
        await update.message.reply_text(INVALID_TIME_FORMAT_MSG)
        return

    until_date = time.time() + duration_sec
    await context.bot.ban_chat_member(chat_id, target_user_id, until_date=int(until_date))
    await update.message.reply_text(f"User banned for {duration_str}.")


@admin_only
@group_management_command_enabled_check("unban")
@bot_has_permissions(["can_restrict_members"])
@error_handler
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(USAGE_UNBAN_MSG)
        return
    user_id = int(context.args[0])
    await context.bot.unban_chat_member(update.effective_chat.id, user_id)
    await update.message.reply_text("User unbanned.")


@admin_only
@group_management_command_enabled_check("purge")
@bot_has_permissions(["can_delete_messages"])
@error_handler
async def purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(USAGE_PURGE_MSG)
        return

    chat_id = update.effective_chat.id
    message_ids_to_delete = []

    try:
        if update.message.reply_to_message:
            start_message_id = update.message.reply_to_message.message_id
            num_messages = int(context.args[0]) if context.args else 1
            for i in range(num_messages):
                message_ids_to_delete.append(start_message_id - i)
        else:
            num_messages = int(context.args[0])
            for i in range(num_messages + 1):
                message_ids_to_delete.append(update.message.message_id - i)

        message_ids_to_delete = sorted(list(set(message_ids_to_delete)))

        deleted_count = 0
        for msg_id in message_ids_to_delete:
            try:
                await context.bot.delete_message(chat_id, msg_id)
                deleted_count += 1
            except Exception as e:
                print(f"Error deleting message {msg_id} in chat {chat_id}: {e}")

        await context.bot.send_message(chat_id, f"Purged {deleted_count} messages.")

    except ValueError:
        await update.message.reply_text(USAGE_PURGE_MSG)
    except Exception as e:
        await update.message.reply_text(f"An error occurred during purge: {e}")


@admin_only
@group_management_command_enabled_check("warn")
@error_handler
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user = update.message.reply_to_message.from_user

    if await is_user_admin(context, chat_id, target_user.id):
        await update.message.reply_text(NO_ADMIN_WARN_MSG)
        return

    group = await load_group(chat_id)

    warn_counts = group.setdefault('warn_counts', {})
    user_id_str = str(target_user.id)
    warn_counts[user_id_str] = warn_counts.get(user_id_str, 0) + 1

    limit = group.get('warn_limit', 3)
    reason = " ".join(context.args).strip()
    default_reason = escape_markdown("No reason specified", version=2)
    reason_text = escape_markdown(reason, version=2) if reason else default_reason

    warn_message = (
        f"Warned {target_user.mention_markdown_v2()} "
        f"\\({warn_counts[user_id_str]}/{limit}\\).\n"
        f"Reason: {reason_text}"
    )

    await update.message.reply_text(warn_message, parse_mode="MarkdownV2")

    if warn_counts[user_id_str] >= limit:
        mode = group.get('warn_mode', 'mute')
        await update.message.reply_text(f"User reached warning limit. Action: {mode.capitalize()}.")
        if mode == 'kick':
            await kick(update, context)
        elif mode == 'ban':
            await ban(update, context)
        else:
            await mute(update, context)
        warn_counts[user_id_str] = 0

    await save_group(chat_id, group)


@admin_only
@group_management_command_enabled_check("warns")
@error_handler
async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user = update.message.reply_to_message.from_user
    group = await load_group(chat_id)

    count = group.get('warn_counts', {}).get(str(target_user.id), 0)
    await update.message.reply_text(
        f"User {target_user.mention_markdown_v2()} has {count} warnings\\.",
        parse_mode="MarkdownV2"
    )


@admin_only
@group_management_command_enabled_check("warnlimit")
@error_handler
async def set_warn_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(USAGE_WARN_LIMIT_MSG)
        return
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)
    group['warn_limit'] = int(context.args[0])
    await save_group(chat_id, group)
    await update.message.reply_text(f"Warning limit set to {context.args[0]}.")


@admin_only
@group_management_command_enabled_check("warnmode")
@error_handler
async def set_warn_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ['mute', 'kick', 'ban']:
        await update.message.reply_text(USAGE_WARN_MODE_MSG)
        return
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)
    group['warn_mode'] = context.args[0].lower()
    await save_group(chat_id, group)
    await update.message.reply_text(f"Warning mode set to {context.args[0].lower()}.")

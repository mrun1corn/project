from functools import wraps
from typing import Dict, Set

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from command_registry import (
    get_default_global_commands,
    get_default_group_commands,
    get_default_notes_commands,
)
from database import get_collection
from settings import settings


GLOBAL_COMMAND_DEFAULTS = get_default_global_commands()
GROUP_COMMAND_DEFAULTS = get_default_group_commands()
NOTES_COMMAND_DEFAULTS = get_default_notes_commands()

CONFIG_COLLECTION = get_collection("bot_config")
CONFIG_ID = "global"

_command_states_cache: Dict[str, bool] | None = None
_approved_users_cache: Set[int] | None = None
_config_backend_error: str | None = None


def is_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != settings.admin_chat_id:
            await update.message.reply_text("🔒 You do not have permission to use this command.")
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


async def _ensure_config() -> tuple[Dict[str, bool], Set[int]]:
    global _command_states_cache, _approved_users_cache, _config_backend_error
    if _command_states_cache is not None and _approved_users_cache is not None:
        return _command_states_cache, _approved_users_cache

    try:
        doc = await CONFIG_COLLECTION.find_one({"_id": CONFIG_ID}) or {}
        stored_states = doc.get("command_states", {})
        merged_states = GLOBAL_COMMAND_DEFAULTS.copy()
        merged_states.update({k: bool(v) for k, v in stored_states.items() if k in GLOBAL_COMMAND_DEFAULTS})

        raw_approved_users = doc.get("approved_users", [])
        approved_users: Set[int] = set()
        for value in raw_approved_users:
            try:
                approved_users.add(int(value))
            except (TypeError, ValueError):
                continue

        if doc.get("_id") is None:
            await CONFIG_COLLECTION.insert_one(
                {"_id": CONFIG_ID, "command_states": merged_states, "approved_users": list(approved_users)}
            )
        else:
            await CONFIG_COLLECTION.update_one(
                {"_id": CONFIG_ID},
                {"$set": {"command_states": merged_states, "approved_users": list(approved_users)}},
                upsert=True,
            )

        _command_states_cache = merged_states
        _approved_users_cache = approved_users
        _config_backend_error = None
        return merged_states, approved_users
    except Exception as exc:
        _config_backend_error = str(exc)
        print(f"Config backend unavailable, falling back to in-memory defaults: {exc}")
        fallback_states = GLOBAL_COMMAND_DEFAULTS.copy()
        fallback_approved_users: Set[int] = {settings.admin_chat_id} if settings.admin_chat_id else set()
        _command_states_cache = fallback_states
        _approved_users_cache = fallback_approved_users
        return fallback_states, fallback_approved_users


async def _set_command_state(command: str, enabled: bool) -> None:
    states, approved = await _ensure_config()
    states[command] = enabled
    try:
        await CONFIG_COLLECTION.update_one(
            {"_id": CONFIG_ID},
            {"$set": {f"command_states.{command}": enabled}},
            upsert=True,
        )
    except Exception as exc:
        print(f"Failed to persist command state for {command}: {exc}")


async def _add_approved_user(user_id: int) -> None:
    user_id = int(user_id)
    states, approved = await _ensure_config()
    approved.add(user_id)
    try:
        await CONFIG_COLLECTION.update_one(
            {"_id": CONFIG_ID},
            {"$addToSet": {"approved_users": user_id}},
            upsert=True,
        )
    except Exception as exc:
        print(f"Failed to persist approved user {user_id}: {exc}")


async def _remove_approved_user(user_id: int) -> None:
    user_id = int(user_id)
    states, approved = await _ensure_config()
    approved.discard(user_id)
    try:
        await CONFIG_COLLECTION.update_one(
            {"_id": CONFIG_ID},
            {"$pull": {"approved_users": user_id}},
            upsert=True,
        )
    except Exception as exc:
        print(f"Failed to persist revoked user {user_id}: {exc}")


def _format_command_overview(include_status: bool = False) -> str:
    lines = []
    states = _command_states_cache or GLOBAL_COMMAND_DEFAULTS
    for command in sorted(GLOBAL_COMMAND_DEFAULTS):
        status = states.get(command, GLOBAL_COMMAND_DEFAULTS[command])
        if include_status:
            state_emoji = "🟢" if status else "🔴"
            lines.append(f"• <code>{command}</code>: {state_emoji}")
        else:
            lines.append(f"• <code>{command}</code>")
    return "\n".join(lines)


def _format_simple_list(names) -> str:
    return "\n".join(f"• <code>{name}</code>" for name in sorted(names))


@is_admin
async def enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    states, _ = await _ensure_config()
    if not context.args:
        overview = _format_command_overview()
        group_list = _format_simple_list(GROUP_COMMAND_DEFAULTS.keys())
        notes_list = _format_simple_list(NOTES_COMMAND_DEFAULTS.keys())
        message = (
            "<b>Enable Command</b>\n"
            "Use <code>/enable &lt;command_name&gt;</code>.\n\n"
            "<b>Global commands</b>\n"
            f"{overview}\n\n"
            "<b>Group commands</b>\n"
            f"{group_list}\n\n"
            "<b>Notes commands</b>\n"
            f"{notes_list}"
        )
        await update.message.reply_text(message, parse_mode="HTML")
        return

    command = context.args[0].lower()
    if command in GLOBAL_COMMAND_DEFAULTS:
        if states.get(command, True):
            await update.message.reply_text(f"ℹ️ <code>{command}</code> is already enabled.", parse_mode="HTML")
        else:
            await _set_command_state(command, True)
            await update.message.reply_text(f"✅ <code>{command}</code> has been enabled.", parse_mode="HTML")
    else:
        overview = _format_command_overview()
        group_list = _format_simple_list(GROUP_COMMAND_DEFAULTS.keys())
        notes_list = _format_simple_list(NOTES_COMMAND_DEFAULTS.keys())
        await update.message.reply_text(
            "<b>Unknown Command</b>\n"
            "I couldn't find that command in the global toggle list.\n\n"
            "<b>Global commands</b>\n"
            f"{overview}\n\n"
            "<b>Group commands</b>\n"
            f"{group_list}\n\n"
            "<b>Notes commands</b>\n"
            f"{notes_list}",
            parse_mode="HTML",
        )


@is_admin
async def disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    states, _ = await _ensure_config()
    if not context.args:
        overview = _format_command_overview()
        group_list = _format_simple_list(GROUP_COMMAND_DEFAULTS.keys())
        notes_list = _format_simple_list(NOTES_COMMAND_DEFAULTS.keys())
        message = (
            "<b>Disable Command</b>\n"
            "Use <code>/disable &lt;command_name&gt;</code>.\n\n"
            "<b>Global commands</b>\n"
            f"{overview}\n\n"
            "<b>Group commands</b>\n"
            f"{group_list}\n\n"
            "<b>Notes commands</b>\n"
            f"{notes_list}"
        )
        await update.message.reply_text(message, parse_mode="HTML")
        return

    command = context.args[0].lower()
    if command in GLOBAL_COMMAND_DEFAULTS:
        if not states.get(command, True):
            await update.message.reply_text(f"ℹ️ <code>{command}</code> is already disabled.", parse_mode="HTML")
        else:
            await _set_command_state(command, False)
            await update.message.reply_text(f"🛑 <code>{command}</code> has been disabled.", parse_mode="HTML")
    else:
        overview = _format_command_overview()
        group_list = _format_simple_list(GROUP_COMMAND_DEFAULTS.keys())
        notes_list = _format_simple_list(NOTES_COMMAND_DEFAULTS.keys())
        await update.message.reply_text(
            "<b>Unknown Command</b>\n"
            "I couldn't find that command in the global toggle list.\n\n"
            "<b>Global commands</b>\n"
            f"{overview}\n\n"
            "<b>Group commands</b>\n"
            f"{group_list}\n\n"
            "<b>Notes commands</b>\n"
            f"{notes_list}",
            parse_mode="HTML",
        )


@is_admin
async def revoke_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        await _remove_approved_user(user_id)
        await update.message.reply_text(f"🚫 User <code>{user_id}</code> has been revoked.", parse_mode="HTML")
    else:
        await update.message.reply_text("↩️ Reply to a user's message to revoke their approval.")


@is_admin
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        await _add_approved_user(target_user_id)
        await update.message.reply_text(f"✅ User <code>{target_user_id}</code> has been approved.", parse_mode="HTML")
        return

    if context.args:
        identifier = context.args[0].strip()
        if identifier.isdigit():
            target_user_id = int(identifier)
            await _add_approved_user(target_user_id)
            await update.message.reply_text(f"✅ User ID <code>{target_user_id}</code> has been approved.", parse_mode="HTML")
            return

        if identifier.startswith('@'):
            username = identifier
            try:
                chat = await context.bot.get_chat(username)
                target_user_id = chat.id
                await _add_approved_user(target_user_id)
                await update.message.reply_text(
                    f"✅ {username} has been approved.\nUser ID: <code>{target_user_id}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                await update.message.reply_text(
                    f"⚠️ I couldn't find {username}. Make sure the username is correct and the user has already interacted with the bot."
                )
            return

    await update.message.reply_text(
        "<b>How To Approve A User</b>\n"
        "Reply to the user's message, or send <code>/approve @username</code> or <code>/approve 123456789</code>.",
        parse_mode="HTML",
    )


async def check_user_approval(user_id: int) -> bool:
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return False

    if user_id == settings.admin_chat_id:
        return True
    _, approved = await _ensure_config()
    return user_id in approved


async def enforce_user_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    if user.id == settings.admin_chat_id:
        return

    is_command = False
    if update.message:
        message = update.message
        if message.entities:
            is_command = any(entity.type == "bot_command" and entity.offset == 0 for entity in message.entities)
        if not is_command and message.caption_entities:
            is_command = any(entity.type == "bot_command" and entity.offset == 0 for entity in message.caption_entities)
        if not is_command and message.text:
            is_command = message.text.strip().startswith("/")
        if not is_command and message.caption:
            is_command = message.caption.strip().startswith("/")
    elif update.callback_query:
        is_command = True

    if not is_command:
        return

    if await check_user_approval(user.id):
        return

    if update.callback_query:
        await update.callback_query.answer("You are not approved to use this bot yet.", show_alert=True)
    elif update.message:
        await update.message.reply_text("⚠️ You are not approved to use this bot yet.")

    raise ApplicationHandlerStop


async def check_command_enabled(command: str) -> bool:
    states, _ = await _ensure_config()
    if command not in GLOBAL_COMMAND_DEFAULTS:
        return True
    return states.get(command, GLOBAL_COMMAND_DEFAULTS[command])


@is_admin
async def list_commands_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_config()
    status_message = "<b>Command Status</b>\n\n"
    status_message += _format_command_overview(include_status=True)
    status_message += "\n\nUse <code>/group_manage</code> or <code>/notes_manage</code> for chat-specific controls."
    if _config_backend_error:
        status_message += "\n\n⚠️ MongoDB is unavailable right now, so these values are using in-memory defaults."
    await update.message.reply_text(status_message, parse_mode="HTML")

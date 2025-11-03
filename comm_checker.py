from functools import wraps
from typing import Dict, Tuple, Set
from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop
from settings import settings
from command_registry import (
    get_default_global_commands,
    get_default_group_commands,
    get_default_notes_commands,
)
from database import get_collection


GLOBAL_COMMAND_DEFAULTS = get_default_global_commands()
GROUP_COMMAND_DEFAULTS = get_default_group_commands()
NOTES_COMMAND_DEFAULTS = get_default_notes_commands()

CONFIG_COLLECTION = get_collection("bot_config")
CONFIG_ID = "global"

_command_states_cache: Dict[str, bool] | None = None
_approved_users_cache: Set[int] | None = None


def is_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != settings.admin_chat_id:
            await update.message.reply_text("You do not have permission to use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


async def _ensure_config() -> Tuple[Dict[str, bool], Set[int]]:
    global _command_states_cache, _approved_users_cache
    if _command_states_cache is not None and _approved_users_cache is not None:
        return _command_states_cache, _approved_users_cache

    doc = await CONFIG_COLLECTION.find_one({"_id": CONFIG_ID}) or {}
    stored_states = doc.get("command_states", {})
    merged_states = GLOBAL_COMMAND_DEFAULTS.copy()
    merged_states.update({k: bool(v) for k, v in stored_states.items() if k in GLOBAL_COMMAND_DEFAULTS})

    approved_users = set(doc.get("approved_users", []))

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
    return merged_states, approved_users


async def _set_command_state(command: str, enabled: bool) -> None:
    states, approved = await _ensure_config()
    states[command] = enabled
    await CONFIG_COLLECTION.update_one(
        {"_id": CONFIG_ID},
        {"$set": {f"command_states.{command}": enabled}},
        upsert=True,
    )


async def _add_approved_user(user_id: int) -> None:
    states, approved = await _ensure_config()
    approved.add(user_id)
    await CONFIG_COLLECTION.update_one(
        {"_id": CONFIG_ID},
        {"$addToSet": {"approved_users": user_id}},
        upsert=True,
    )


async def _remove_approved_user(user_id: int) -> None:
    states, approved = await _ensure_config()
    approved.discard(user_id)
    await CONFIG_COLLECTION.update_one(
        {"_id": CONFIG_ID},
        {"$pull": {"approved_users": user_id}},
        upsert=True,
    )


def _format_command_overview(include_status: bool = False) -> str:
    lines = []
    states = _command_states_cache or GLOBAL_COMMAND_DEFAULTS
    for command in sorted(GLOBAL_COMMAND_DEFAULTS):
        status = states.get(command, GLOBAL_COMMAND_DEFAULTS[command])
        if include_status:
            state_text = "Enabled" if status else "Disabled"
            lines.append(f"- {command}: {state_text}")
        else:
            lines.append(f"- {command}")
    return "\n".join(lines)


def _format_simple_list(names) -> str:
    return "\n".join(f"- {name}" for name in sorted(names))


@is_admin
async def enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable a command."""
    states, _ = await _ensure_config()
    if not context.args:
        overview = _format_command_overview()
        group_list = _format_simple_list(GROUP_COMMAND_DEFAULTS.keys())
        notes_list = _format_simple_list(NOTES_COMMAND_DEFAULTS.keys())
        message = (
            "Usage: /enable <command_name>\n\n"
            "Global commands:\n"
            f"{overview}\n\n"
            "Group commands (manage with /group_manage):\n"
            f"{group_list}\n\n"
            "Notes commands (manage with /notes_manage):\n"
            f"{notes_list}"
        )
        await update.message.reply_text(message)
        return

    command = context.args[0].lower()
    if command in GLOBAL_COMMAND_DEFAULTS:
        if states.get(command, True):
            await update.message.reply_text(f"{command} command is already enabled.")
        else:
            await _set_command_state(command, True)
            await update.message.reply_text(f"{command} command has been enabled.")
    else:
        overview = _format_command_overview()
        group_list = _format_simple_list(GROUP_COMMAND_DEFAULTS.keys())
        notes_list = _format_simple_list(NOTES_COMMAND_DEFAULTS.keys())
        await update.message.reply_text(
            "Invalid command.\n\n"
            "Global commands:\n"
            f"{overview}\n\n"
            "Group commands (manage with /group_manage):\n"
            f"{group_list}\n\n"
            "Notes commands (manage with /notes_manage):\n"
            f"{notes_list}"
        )


@is_admin
async def disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable a command."""
    states, _ = await _ensure_config()
    if not context.args:
        overview = _format_command_overview()
        group_list = _format_simple_list(GROUP_COMMAND_DEFAULTS.keys())
        notes_list = _format_simple_list(NOTES_COMMAND_DEFAULTS.keys())
        message = (
            "Usage: /disable <command_name>\n\n"
            "Global commands:\n"
            f"{overview}\n\n"
            "Group commands (manage with /group_manage):\n"
            f"{group_list}\n\n"
            "Notes commands (manage with /notes_manage):\n"
            f"{notes_list}"
        )
        await update.message.reply_text(message)
        return

    command = context.args[0].lower()
    if command in GLOBAL_COMMAND_DEFAULTS:
        if not states.get(command, True):
            await update.message.reply_text(f"{command} command is already disabled.")
        else:
            await _set_command_state(command, False)
            await update.message.reply_text(f"{command} command has been disabled.")
    else:
        overview = _format_command_overview()
        group_list = _format_simple_list(GROUP_COMMAND_DEFAULTS.keys())
        notes_list = _format_simple_list(NOTES_COMMAND_DEFAULTS.keys())
        await update.message.reply_text(
            "Invalid command.\n\n"
            "Global commands:\n"
            f"{overview}\n\n"
            "Group commands (manage with /group_manage):\n"
            f"{group_list}\n\n"
            "Notes commands (manage with /notes_manage):\n"
            f"{notes_list}"
        )


@is_admin
async def revoke_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoke a user's approval to access commands."""
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        await _remove_approved_user(user_id)
        await update.message.reply_text(f"User {user_id} has been revoked from access.")
    else:
        await update.message.reply_text("Please reply to the user's message to revoke their approval.")


@is_admin
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve a user to access all commands by reply, username, or user ID."""
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        await _add_approved_user(target_user_id)
        await update.message.reply_text(f"User {target_user_id} has been approved.")
        return

    if context.args:
        identifier = context.args[0].strip()
        if identifier.isdigit():
            target_user_id = int(identifier)
            await _add_approved_user(target_user_id)
            await update.message.reply_text(f"User with ID {target_user_id} has been approved.")
            return

        if identifier.startswith('@'):
            username = identifier
            try:
                chat = await context.bot.get_chat(username)
                target_user_id = chat.id
                await _add_approved_user(target_user_id)
                await update.message.reply_text(f"User {username} (ID: {target_user_id}) has been approved.")
            except Exception:
                await update.message.reply_text(
                    f"Error: Could not find user {username}. Ensure the username is correct and the user has interacted with the bot."
                )
            return

    await update.message.reply_text(
        "Please reply to a user's message, or provide a username (e.g., @username) or user ID (e.g., 123456789)."
    )


async def check_user_approval(user_id: int) -> bool:
    """Check if a user is approved before allowing commands."""
    if user_id == settings.admin_chat_id:
        return True
    _, approved = await _ensure_config()
    return user_id in approved


async def enforce_user_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Block unapproved users from interacting with the bot."""
    user = update.effective_user
    if not user:
        return
    if user.id == settings.admin_chat_id:
        return
    if await check_user_approval(user.id):
        return

    if update.callback_query:
        await update.callback_query.answer("❌ You are not approved to use this bot.", show_alert=True)
    elif update.message:
        await update.message.reply_text("❌ You are not approved to use this bot.")

    raise ApplicationHandlerStop


async def check_command_enabled(command: str) -> bool:
    """Check if a command is enabled."""
    states, _ = await _ensure_config()
    if command not in GLOBAL_COMMAND_DEFAULTS:
        return True
    return states.get(command, GLOBAL_COMMAND_DEFAULTS[command])


@is_admin
async def list_commands_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists the current status (enabled/disabled) of all toggleable commands."""
    await _ensure_config()
    status_message = "📊 Command Status:\n\n"
    status_message += _format_command_overview(include_status=True)
    status_message += "\n\nℹ️ Use /group_manage or /notes_manage for chat-specific command controls."
    await update.message.reply_text(status_message)

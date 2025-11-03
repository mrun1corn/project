from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from settings import settings
from command_registry import get_default_group_commands
from database import get_collection


GROUP_MANAGEMENT_COMMANDS = get_default_group_commands()
COLLECTION = get_collection("group_management_command_states")


async def _get_chat_states(chat_id: int) -> dict:
    doc = await COLLECTION.find_one({"_id": chat_id})
    if not doc:
        return GROUP_MANAGEMENT_COMMANDS.copy()
    stored = doc.get("commands", {})
    merged = GROUP_MANAGEMENT_COMMANDS.copy()
    merged.update({k: bool(v) for k, v in stored.items() if k in GROUP_MANAGEMENT_COMMANDS})
    return merged


async def _save_chat_states(chat_id: int, states: dict) -> None:
    await COLLECTION.update_one(
        {"_id": chat_id},
        {"$set": {"commands": states}},
        upsert=True,
    )


def group_management_command_enabled_check(command_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            chat_id = update.effective_chat.id
            states = await _get_chat_states(chat_id)
            if not states.get(command_name, True):
                return
            return await func(update, context, *args, **kwargs)
        return wrapped
    return decorator


async def _build_group_manage_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    chat_states = await _get_chat_states(chat_id)
    sorted_commands = sorted(chat_states.items())
    keyboard = []
    row = []
    for i, (cmd, enabled) in enumerate(sorted_commands):
        status_icon = "✅" if enabled else "❌"
        button = InlineKeyboardButton(f"{status_icon} {cmd.capitalize()}", callback_data=f"group_manage_toggle_{cmd}")
        if i % 2 == 0:
            keyboard.append([button])
        else:
            keyboard[-1].append(button)
    keyboard.append([
        InlineKeyboardButton("✅ Enable All", callback_data="group_manage_all_enable"),
        InlineKeyboardButton("❌ Disable All", callback_data="group_manage_all_disable")
    ])
    return InlineKeyboardMarkup(keyboard)


async def group_manage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if update.effective_user.id != settings.admin_chat_id:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    reply_markup = await _build_group_manage_keyboard(chat_id)
    await update.message.reply_text("🔧 *Manage Group Management Commands:*", reply_markup=reply_markup, parse_mode="Markdown")


async def group_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat.id
    if query.from_user.id != settings.admin_chat_id:
        await query.answer("❌ You are not authorized to change these settings.", show_alert=True)
        return

    data = query.data
    chat_states = await _get_chat_states(chat_id)

    if data == "group_manage_all_enable":
        if all(chat_states.values()):
            await query.answer("All group management commands are already enabled.")
            return
        for cmd in chat_states:
            chat_states[cmd] = True
        await _save_chat_states(chat_id, chat_states)
        reply_markup = await _build_group_manage_keyboard(chat_id)
        await query.edit_message_text("✅ All group management commands enabled.", reply_markup=reply_markup)
    elif data == "group_manage_all_disable":
        if all(not status for status in chat_states.values()):
            await query.answer("All group management commands are already disabled.")
            return
        for cmd in chat_states:
            chat_states[cmd] = False
        await _save_chat_states(chat_id, chat_states)
        reply_markup = await _build_group_manage_keyboard(chat_id)
        await query.edit_message_text("❌ All group management commands disabled.", reply_markup=reply_markup)
    elif data.startswith("group_manage_toggle_"):
        command_name = data.replace("group_manage_toggle_", "")
        if command_name in chat_states:
            chat_states[command_name] = not chat_states[command_name]
            await _save_chat_states(chat_id, chat_states)
            status = "enabled" if chat_states[command_name] else "disabled"
            reply_markup = await _build_group_manage_keyboard(chat_id)
            await query.edit_message_text(f"✅ Command `{command_name}` is now {status}.", reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Invalid command selected.")

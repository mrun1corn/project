import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from functools import wraps
import json
from config import ADMIN_CHAT_ID
from command_registry import get_default_group_commands

# Define all commands that can be enabled/disabled in group_management.py
GROUP_MANAGEMENT_COMMANDS = get_default_group_commands()

GROUP_MANAGEMENT_STATES_FILE = 'group_management_command_states.json'

_all_group_management_command_states = {}

def load_group_management_command_states():
    global _all_group_management_command_states
    try:
        if os.path.exists(GROUP_MANAGEMENT_STATES_FILE):
            with open(GROUP_MANAGEMENT_STATES_FILE, 'r') as f:
                _all_group_management_command_states = json.load(f).get('group_management_commands', {})
        else:
            _all_group_management_command_states = {}
    except (FileNotFoundError, json.JSONDecodeError):
        _all_group_management_command_states = {}

    # Ensure all chats have all default commands
    for chat_id_str, chat_states in list(_all_group_management_command_states.items()): # Use list() to iterate over a copy
        if not isinstance(chat_states, dict):
            # Data for this chat_id is corrupted, re-initialize it to default
            _all_group_management_command_states[chat_id_str] = GROUP_MANAGEMENT_COMMANDS.copy()
            chat_states = _all_group_management_command_states[chat_id_str] # Update chat_states reference

        for cmd, default_status in GROUP_MANAGEMENT_COMMANDS.items():
            if cmd not in chat_states:
                chat_states[cmd] = default_status
        # Remove any commands from loaded_states that are no longer in GROUP_MANAGEMENT_COMMANDS
        commands_to_remove = [cmd for cmd in chat_states if cmd not in GROUP_MANAGEMENT_COMMANDS]
        for cmd in commands_to_remove:
            del chat_states[cmd]


def save_group_management_command_states():
    try:
        with open(GROUP_MANAGEMENT_STATES_FILE, 'w') as f:
            json.dump({'group_management_commands': _all_group_management_command_states}, f, indent=4)
    except IOError as e:
        print(f"Error saving group management command states: {e}")

load_group_management_command_states()

def check_group_management_command_enabled(chat_id: int, command: str) -> bool:
    chat_id_str = str(chat_id)
    if chat_id_str not in _all_group_management_command_states:
        # If chat not found, initialize with default commands
        _all_group_management_command_states[chat_id_str] = GROUP_MANAGEMENT_COMMANDS.copy()
        save_group_management_command_states()
    return _all_group_management_command_states[chat_id_str].get(command, True)

def group_management_command_enabled_check(command_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            chat_id = update.effective_chat.id
            if not check_group_management_command_enabled(chat_id, command_name):
                return
            return await func(update, context, *args, **kwargs)
        return wrapped
    return decorator

def _build_group_manage_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    keyboard = []
    chat_states = _all_group_management_command_states.get(str(chat_id), GROUP_MANAGEMENT_COMMANDS.copy())
    sorted_commands = sorted(chat_states.items())
    for i, (cmd, enabled) in enumerate(sorted_commands):
        status_icon = "✅" if enabled else "❌"
        button = InlineKeyboardButton(f"{status_icon} {cmd.capitalize()}", callback_data=f"group_manage_toggle_{cmd}")
        
        if i % 2 == 0: # Start a new row for every two buttons
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
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    reply_markup = _build_group_manage_keyboard(chat_id)
    await update.message.reply_text("🔧 *Manage Group Management Commands:*", reply_markup=reply_markup, parse_mode="Markdown")

async def group_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat.id
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("❌ You are not authorized to change these settings.", show_alert=True)
        return

    data = query.data
    chat_states = _all_group_management_command_states.setdefault(str(chat_id), GROUP_MANAGEMENT_COMMANDS.copy())

    if data == "group_manage_all_enable":
        # Check if all are already enabled
        all_enabled = all(chat_states.values())
        if all_enabled:
            await query.answer("All group management commands are already enabled.")
            return
        for cmd in chat_states:
            chat_states[cmd] = True
        save_group_management_command_states()
        await query.edit_message_text("✅ All group management commands enabled.", reply_markup=_build_group_manage_keyboard(chat_id))
    elif data == "group_manage_all_disable":
        # Check if all are already disabled
        all_disabled = all(not status for status in chat_states.values())
        if all_disabled:
            await query.answer("All group management commands are already disabled.")
            return
        for cmd in chat_states:
            chat_states[cmd] = False
        save_group_management_command_states()
        await query.edit_message_text("❌ All group management commands disabled.", reply_markup=_build_group_manage_keyboard(chat_id))
    elif data.startswith("group_manage_toggle_"):
        command_name = data.replace("group_manage_toggle_", "")
        if command_name in chat_states:
            old_status = chat_states[command_name]
            chat_states[command_name] = not old_status
            if old_status == chat_states[command_name]: # No actual change
                await query.answer("No changes were made.")
                return
            save_group_management_command_states()
            status = "enabled" if chat_states[command_name] else "disabled"
            await query.edit_message_text(f"✅ Command `{command_name}` is now {status}.", reply_markup=_build_group_manage_keyboard(chat_id), parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Invalid command selected.")

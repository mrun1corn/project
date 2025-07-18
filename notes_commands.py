import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from functools import wraps
from config import ADMIN_CHAT_ID
from group_management import error_handler

# Define all commands that can be enabled/disabled in notes.py
NOTES_COMMANDS = {
    'keep': True,
    'notes': True,
    'delete': True,
    'getnote': True, # This is handled by Regex filter, but we can still toggle its functionality
}

NOTES_STATES_FILE = 'notes_command_states.json'

def load_notes_command_states():
    try:
        if os.path.exists(NOTES_STATES_FILE):
            with open(NOTES_STATES_FILE, 'r') as f:
                loaded_states = json.load(f).get('notes_commands', {})
        else:
            loaded_states = {}
    except (FileNotFoundError, json.JSONDecodeError):
        loaded_states = {}

    for cmd, default_status in NOTES_COMMANDS.items():
        if cmd not in loaded_states:
            loaded_states[cmd] = default_status
    
    commands_to_remove = [cmd for cmd in loaded_states if cmd not in NOTES_COMMANDS]
    for cmd in commands_to_remove:
        del loaded_states[cmd]

    return loaded_states

def save_notes_command_states(states):
    try:
        with open(NOTES_STATES_FILE, 'w') as f:
            json.dump({'notes_commands': states}, f, indent=4)
    except IOError as e:
        print(f"Error saving notes command states: {e}")

notes_command_states = load_notes_command_states()

def check_notes_command_enabled(command: str) -> bool:
    return notes_command_states.get(command, True)

def notes_command_enabled_check(command_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not check_notes_command_enabled(command_name):
                return
            return await func(update, context, *args, **kwargs)
        return wrapped
    return decorator

def _build_notes_manage_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    sorted_commands = sorted(notes_command_states.items())
    for i, (cmd, enabled) in enumerate(sorted_commands):
        status_icon = "✅" if enabled else "❌"
        button = InlineKeyboardButton(f"{status_icon} {cmd.capitalize()}", callback_data=f"notes_manage_toggle_{cmd}")
        
        if i % 2 == 0: # Two columns
            keyboard.append([button])
        else:
            keyboard[-1].append(button)
    
    keyboard.append([
        InlineKeyboardButton("✅ Enable All", callback_data="notes_manage_all_enable"),
        InlineKeyboardButton("❌ Disable All", callback_data="notes_manage_all_disable")
    ])
    return InlineKeyboardMarkup(keyboard)

async def notes_manage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    reply_markup = _build_notes_manage_keyboard()
    await update.message.reply_text("🔧 *Manage Notes Commands:*", reply_markup=reply_markup, parse_mode="Markdown")

async def notes_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ You are not authorized to change these settings.")
        return

    data = query.data

    if data == "notes_manage_all_enable":
        for cmd in notes_command_states:
            notes_command_states[cmd] = True
        save_notes_command_states(notes_command_states)
        await query.edit_message_text("✅ All notes commands enabled.", reply_markup=_build_notes_manage_keyboard())
    elif data == "notes_manage_all_disable":
        for cmd in notes_command_states:
            notes_command_states[cmd] = False
        save_notes_command_states(notes_command_states)
        await query.edit_message_text("❌ All notes commands disabled.", reply_markup=_build_notes_manage_keyboard())
    elif data.startswith("notes_manage_toggle_"):
        command_name = data.replace("notes_manage_toggle_", "")
        if command_name in notes_command_states:
            notes_command_states[command_name] = not notes_command_states[command_name]
            save_notes_command_states(notes_command_states)
            status = "enabled" if notes_command_states[command_name] else "disabled"
            await query.edit_message_text(f"✅ Command `{command_name}` is now {status}.", reply_markup=_build_notes_manage_keyboard(), parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Invalid command selected.")

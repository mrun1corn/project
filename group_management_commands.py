import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from functools import wraps
import json
from config import ADMIN_CHAT_ID

# Define all commands that can be enabled/disabled in group_management.py
GROUP_MANAGEMENT_COMMANDS = {
    'welcome': True,
    'goodbye': True,
    'filter': True,
    'stop': True,
    'mute': True,
    'tmute': True,
    'unmute': True,
    'kick': True,
    'ban': True,
    'tban': True,
    'unban': True,
    'warn': True,
    'warns': True,
    'warnlimit': True,
    'warnmode': True,
    'locks': True,
    'pin': True,
    'action': True,
    'promote': True,
    'demote': True,
    'permissions': True,
    'tagadmin': True,
}

GROUP_MANAGEMENT_STATES_FILE = 'group_management_command_states.json'

def load_group_management_command_states():
    try:
        if os.path.exists(GROUP_MANAGEMENT_STATES_FILE):
            with open(GROUP_MANAGEMENT_STATES_FILE, 'r') as f:
                loaded_states = json.load(f).get('group_management_commands', {})
        else:
            loaded_states = {}
    except (FileNotFoundError, json.JSONDecodeError):
        loaded_states = {}

    # Merge loaded states with default commands, ensuring all defaults are present
    # and loaded states override defaults if they exist.
    for cmd, default_status in GROUP_MANAGEMENT_COMMANDS.items():
        if cmd not in loaded_states:
            loaded_states[cmd] = default_status
    
    # Remove any commands from loaded_states that are no longer in GROUP_MANAGEMENT_COMMANDS
    commands_to_remove = [cmd for cmd in loaded_states if cmd not in GROUP_MANAGEMENT_COMMANDS]
    for cmd in commands_to_remove:
        del loaded_states[cmd]

    return loaded_states

def save_group_management_command_states(states):
    try:
        with open(GROUP_MANAGEMENT_STATES_FILE, 'w') as f:
            json.dump({'group_management_commands': states}, f, indent=4)
    except IOError as e:
        print(f"Error saving group management command states: {e}")

group_management_command_states = load_group_management_command_states()

def check_group_management_command_enabled(command: str) -> bool:
    return group_management_command_states.get(command, True)

def group_management_command_enabled_check(command_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not check_group_management_command_enabled(command_name):
                return
            return await func(update, context, *args, **kwargs)
        return wrapped
    return decorator

def _build_group_manage_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    sorted_commands = sorted(group_management_command_states.items())
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
    if update.effective_user.id != ADMIN_CHAT_ID: # Directly use imported ADMIN_CHAT_ID
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    reply_markup = _build_group_manage_keyboard()
    await update.message.reply_text("🔧 *Manage Group Management Commands:*", reply_markup=reply_markup, parse_mode="Markdown")

async def group_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ You are not authorized to change these settings.")
        return

    data = query.data

    if data == "group_manage_all_enable":
        for cmd in group_management_command_states:
            group_management_command_states[cmd] = True
        save_group_management_command_states(group_management_command_states)
        await query.edit_message_text("✅ All group management commands enabled.", reply_markup=_build_group_manage_keyboard())
    elif data == "group_manage_all_disable":
        for cmd in group_management_command_states:
            group_management_command_states[cmd] = False
        save_group_management_command_states(group_management_command_states)
        await query.edit_message_text("❌ All group management commands disabled.", reply_markup=_build_group_manage_keyboard())
    elif data.startswith("group_manage_toggle_"):
        command_name = data.replace("group_manage_toggle_", "")
        if command_name in group_management_command_states:
            group_management_command_states[command_name] = not group_management_command_states[command_name]
            save_group_management_command_states(group_management_command_states)
            status = "enabled" if group_management_command_states[command_name] else "disabled"
            await query.edit_message_text(f"✅ Command `{command_name}` is now {status}.", reply_markup=_build_group_manage_keyboard(), parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Invalid command selected.")

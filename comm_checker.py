from telegram import Update
from telegram.ext import ContextTypes
import json
from config import ADMIN_CHAT_ID
from functools import wraps

def is_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != ADMIN_CHAT_ID:
            await update.message.reply_text("You do not have permission to use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def load_command_states():
    try:
        with open('command_states.json', 'r') as f:
            loaded_states = json.load(f).get('command_states', {})
    except (FileNotFoundError, json.JSONDecodeError):
        loaded_states = {}

    # Define all commands that can be enabled/disabled
    # Initialize them to True if not already in loaded_states
    default_commands = {
        'shell': True,
        'help': True,
        'ai': True,
        'speedtest': True,
        'ping': True,
        'reboot': True,
        'music': True,
        'video': True,
        'reel': True,
        'bgremove': True,
        'store': True,
        'getnote': True,
        'listnotes': True,
        'deletenote': True,
        # Add any other commands you want to be toggleable here
    }

    # Merge loaded states with default commands, ensuring all defaults are present
    # and loaded states override defaults if they exist.
    for cmd, default_status in default_commands.items():
        if cmd not in loaded_states:
            loaded_states[cmd] = default_status
    
    # Remove any commands from loaded_states that are no longer in default_commands
    # This handles cases where commands are removed from the bot.
    commands_to_remove = [cmd for cmd in loaded_states if cmd not in default_commands]
    for cmd in commands_to_remove:
        del loaded_states[cmd]

    return loaded_states

# Save command states to a JSON file
def save_command_states(states):
    try:
        with open('command_states.json', 'w') as f:
            json.dump({'command_states': states}, f)
    except IOError as e:
        print(f"Error saving command states: {e}")

# Load approved users from a JSON file
def load_approved_users():
    try:
        with open('approved_users.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []  # Return an empty list if the file doesn't exist

# Save approved users to a JSON file
def save_approved_users(users):
    try:
        with open('approved_users.json', 'w') as f:
            json.dump(users, f)
    except IOError as e:
        print(f"Error saving approved users: {e}")

# Global variables to keep track of command states and approved users
command_states = load_command_states()
approved_users = load_approved_users()

@is_admin
async def enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable a command."""
    if not context.args:
        await update.message.reply_text("Usage: /enable <command_name>")
        return

    command = context.args[0].lower() # Convert to lower for consistency
    if command in command_states:
        if command_states[command]:
            await update.message.reply_text(f"{command} command is already enabled.")
        else:
            command_states[command] = True
            save_command_states(command_states)
            await update.message.reply_text(f"{command} command has been enabled.")
    else:
        await update.message.reply_text("Invalid command. Available commands: " + ", ".join(command_states.keys()))

@is_admin
async def disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable a command."""
    if not context.args:
        await update.message.reply_text("Usage: /disable <command_name>")
        return

    command = context.args[0].lower() # Convert to lower for consistency
    if command in command_states:
        if not command_states[command]:
            await update.message.reply_text(f"{command} command is already disabled.")
        else:
            command_states[command] = False
            save_command_states(command_states)
            await update.message.reply_text(f"{command} command has been disabled.")
    else:
        await update.message.reply_text("Invalid command. Available commands: " + ", ".join(command_states.keys()))

@is_admin
async def revoke_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoke a user's approval to access commands."""
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        if user_id in approved_users:
            approved_users.remove(user_id)  # Remove user from the approved list
            save_approved_users(approved_users)  # Save updated approved users
            await update.message.reply_text(f"User {user_id} has been revoked from access.")
        else:
            await update.message.reply_text("This user is not approved.")
    else:
        await update.message.reply_text("Please reply to the user's message to revoke their approval.")

@is_admin
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve a user to access all commands by reply, username, or user ID."""
    # Option 1: Approve by replying to a message
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        if target_user_id not in approved_users:
            approved_users.append(target_user_id)  # Add user to the approved list
            save_approved_users(approved_users)  # Save approved users
            await update.message.reply_text(f"User {target_user_id} has been approved.")
        else:
            await update.message.reply_text("This user is already approved.")
        return

    # Option 2: Approve by username or user ID
    if context.args:
        identifier = context.args[0].strip()
        
        # Check if the identifier is a user ID (numeric)
        if identifier.isdigit():
            target_user_id = int(identifier)
            if target_user_id not in approved_users:
                approved_users.append(target_user_id)  # Add user to the approved list
                save_approved_users(approved_users)  # Save approved users
                await update.message.reply_text(f"User with ID {target_user_id} has been approved.")
            else:
                await update.message.reply_text(f"User with ID {target_user_id} is already approved.")
            return
        
        # Check if the identifier is a username (starts with @)
        if identifier.startswith('@'):
            username = identifier
            try:
                # Try to resolve username to user ID via Telegram API
                chat = await context.bot.get_chat(username)
                target_user_id = chat.id
                if target_user_id not in approved_users:
                    approved_users.append(target_user_id)  # Add user to the approved list
                    save_approved_users(approved_users)  # Save approved users
                    await update.message.reply_text(f"User {username} (ID: {target_user_id}) has been approved.")
                else:
                    await update.message.reply_text(f"User {username} is already approved.")
            except Exception as e:
                await update.message.reply_text(f"Error: Could not find user {username}. Ensure the username is correct and the user has interacted with the bot.")
            return

    # If no valid input is provided
    await update.message.reply_text("Please reply to a user's message, or provide a username (e.g., @username) or user ID (e.g., 123456789).")

async def check_user_approval(user_id) -> bool:
    """Check if a user is approved before allowing commands."""
    if user_id == ADMIN_CHAT_ID:  # Check if the user is admin
        return True
    return user_id in approved_users  # Check if the user is in the approved list

async def check_command_enabled(command: str) -> bool:
    """Check if a command is enabled."""
    return command_states.get(command, True)  # Default to enabled if not found

@is_admin
async def list_commands_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists the current status (enabled/disabled) of all toggleable commands."""
    status_message = "📊 *Command Status:*\n\n"
    if not command_states:
        status_message += "No commands found to manage."
    else:
        for command, enabled in sorted(command_states.items()):
            status = "✅ Enabled" if enabled else "❌ Disabled"
            status_message += f"- `{command}`: {status}\n"
    
    await update.message.reply_text(status_message, parse_mode="Markdown")
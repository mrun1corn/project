from telegram import Update
from telegram.ext import ContextTypes
import json
from config import ADMIN_CHAT_ID

def load_command_states():
    try:
        with open('command_states.json', 'r') as f:
            data = json.load(f)
            return data.get('command_states', {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            'reboot': True,
            'speedtest': True,
            'ping': True,
            'music': True,
            'shell': True,
            'video': True,
            'bgremove': True,
            'ai': True,
            'help': True,
            'store': True,
            'getnote': True,
            'listnotes': True,
            'deletenote': True
        }

# Save command states to a JSON file
def save_command_states(states):
    with open('command_states.json', 'w') as f:
        json.dump({'command_states': states}, f)

# Load approved users from a JSON file
def load_approved_users():
    try:
        with open('approved_users.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []  # Return an empty list if the file doesn't exist

# Save approved users to a JSON file
def save_approved_users(users):
    with open('approved_users.json', 'w') as f:
        json.dump(users, f)

# Global variables to keep track of command states and approved users
command_states = load_command_states()
approved_users = load_approved_users()

async def enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable a command."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return  # Do not respond to non-admin users
    
    command = context.args[0] if context.args else None
    if command in command_states:
        command_states[command] = True
        save_command_states(command_states)  # Save updated states
        await update.message.reply_text(f"{command} command has been enabled.")
    else:
        await update.message.reply_text("Invalid command. Available commands: " + ", ".join(command_states.keys()))

async def disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable a command."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return  # Do not respond to non-admin users

    command = context.args[0] if context.args else None
    if command in command_states:
        if command_states[command] is False:
            return  # Do not respond if the command is already disabled
        else:
            command_states[command] = False
            save_command_states(command_states)  # Save updated states
            await update.message.reply_text(f"{command} command has been disabled.")
    else:
        await update.message.reply_text("Invalid command. Available commands: " + ", ".join(command_states.keys()))

async def revoke_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoke a user's approval to access commands."""
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:  # If the user is not admin
        await update.message.reply_text("You do not have permission to use this command.")
        return    
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

async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve a user to access all commands by reply, username, or user ID."""
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:  # If the user is not admin
        await update.message.reply_text("You do not have permission to use this command.")
        return    

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
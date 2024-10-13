from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
import subprocess
from config import ADMIN_CHAT_ID

# Dictionary to hold the user's shell state
user_shell_states = {}

async def start_shell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start an interactive shell session."""
    user_id = update.effective_user.id

    # Check if user is an admin
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("You do not have permission to use this command.")
        return

    await update.message.reply_text("Starting shell. Type 'exit' to quit.")
    user_shell_states[user_id] = []  # Initialize the user's shell state

async def handle_shell_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user input for the shell."""
    user_id = update.effective_user.id

    # Check if the user is in a shell session
    if user_id not in user_shell_states:
        return  # Ignore messages if not in shell session

    command = update.message.text.strip()

    # Exit command
    if command.lower() == 'exit':
        await update.message.reply_text("Exiting shell.")
        del user_shell_states[user_id]  # Remove user from shell states
        return

    # Execute the command
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        output = result.stdout if result.returncode == 0 else result.stderr

        # Limit output length
        if len(output) > 4096:
            output = output[:4096] + "\n... (output truncated)"
        
        await update.message.reply_text(f"Command executed:\n```\n{output}\n```", parse_mode='MarkdownV2')

    except Exception as e:
        await update.message.reply_text(f"Error executing command: {e}")

# Add command and input handlers in a single function
def register_shell_handlers(application) -> None:
    """Register shell command handlers."""
    application.add_handler(CommandHandler('shell', start_shell))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_shell_input))

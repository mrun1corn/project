from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import subprocess
import os
from config import ADMIN_CHAT_ID

# Dictionary to hold the user's shell state including current directory
user_shell_states = {}

class ShellSession:
    def __init__(self, cwd=None):
        self.cwd = cwd or os.getcwd()
        self.history = []
        self.env = os.environ.copy()

async def start_shell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start an interactive shell session."""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("You do not have permission to use this command.")
        return
    
    # Initialize shell session with current working directory
    user_shell_states[user_id] = ShellSession()
    
    # Create keyboard with common commands
    keyboard = [
        [
            InlineKeyboardButton("pwd", callback_data="cmd_pwd"),
            InlineKeyboardButton("ls", callback_data="cmd_ls"),
            InlineKeyboardButton("clear", callback_data="cmd_clear")
        ],
        [
            InlineKeyboardButton("cd ..", callback_data="cmd_cd_up"),
            InlineKeyboardButton("ps", callback_data="cmd_ps"),
            InlineKeyboardButton("exit", callback_data="cmd_exit")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🖥 Interactive Shell Started\n"
        f"Current Directory: {user_shell_states[user_id].cwd}\n"
        f"Type commands or use quick actions below:",
        reply_markup=reply_markup
    )

async def handle_shell_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user input for the shell."""
    user_id = update.effective_user.id
    
    if user_id not in user_shell_states:
        return
    
    command = update.message.text.strip()
    shell_session = user_shell_states[user_id]
    
    if command.lower() == 'exit':
        await exit_shell(update, user_id)
        return
        
    # Handle cd commands specially
    if command.startswith('cd '):
        new_dir = command[3:].strip()
        try:
            # Handle relative and absolute paths
            new_path = os.path.abspath(os.path.join(shell_session.cwd, new_dir))
            os.chdir(new_path)
            shell_session.cwd = new_path
            await update.message.reply_text(f"Changed directory to: {shell_session.cwd}")
            return
        except Exception as e:
            await update.message.reply_text(f"Error changing directory: {str(e)}")
            return

    try:
        # Execute command in the current working directory
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=shell_session.cwd,
            env=shell_session.env
        )
        
        stdout, stderr = process.communicate(timeout=30)  # 30 second timeout
        
        output = stdout if process.returncode == 0 else stderr
        shell_session.history.append(command)
        
        # Format and send output
        if output:
            # Escape special characters for MarkdownV2
            output = output.replace('```', '\\`\\`\\`')
            if len(output) > 4000:
                output = output[:4000] + "\n... (output truncated)"
            
            await update.message.reply_text(
                f"```\n{output}\n```",
                parse_mode='MarkdownV2'
            )
        else:
            await update.message.reply_text("Command executed (no output)")
            
    except subprocess.TimeoutExpired:
        await update.message.reply_text("Command timed out after 30 seconds")
    except Exception as e:
        await update.message.reply_text(f"Error executing command: {str(e)}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries from inline keyboard."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_shell_states:
        await query.answer("No active shell session")
        return
        
    cmd = query.data.replace("cmd_", "")
    
    if cmd == "exit":
        await exit_shell(query, user_id)
    elif cmd == "pwd":
        await query.message.reply_text(f"Current directory: {user_shell_states[user_id].cwd}")
    elif cmd == "ls":
        await handle_shell_input(update, context)
    elif cmd == "clear":
        user_shell_states[user_id].history.clear()
        await query.message.reply_text("Command history cleared")
    elif cmd == "cd_up":
        shell_session = user_shell_states[user_id]
        new_path = os.path.dirname(shell_session.cwd)
        os.chdir(new_path)
        shell_session.cwd = new_path
        await query.message.reply_text(f"Changed directory to: {new_path}")
    elif cmd == "ps":
        await handle_shell_input(update, context)
        
    await query.answer()

async def exit_shell(update: Update, user_id: int) -> None:
    """Exit the shell session."""
    if user_id in user_shell_states:
        del user_shell_states[user_id]
        msg_obj = update.message if hasattr(update, 'message') else update.effective_message
        await msg_obj.reply_text("Shell session terminated.")

def register_shell_handlers(application) -> None:
    """Register shell command handlers."""
    application.add_handler(CommandHandler('shell', start_shell))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_shell_input))
    application.add_handler(CallbackQueryHandler(handle_callback))
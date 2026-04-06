import html
import os
import shlex
import subprocess

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from command_template import CommandSpec, guard_command


user_shell_states = {}


class ShellSession:
    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd or os.getcwd()
        self.history: list[str] = []
        self.env = os.environ.copy()


def _split_command(command: str) -> list[str]:
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-Command", command]
    return shlex.split(command, posix=True)


def _format_output(output: str) -> str:
    if len(output) > 4000:
        output = output[:4000] + "\n... (output truncated)"
    return f"<pre>{html.escape(output)}</pre>"


def _get_shell_session(user_id: int) -> ShellSession | None:
    return user_shell_states.get(user_id)


async def _run_command(update: Update, command: str) -> None:
    user_id = update.effective_user.id
    shell_session = _get_shell_session(user_id)
    if shell_session is None:
        await update.effective_message.reply_text("⚠️ No active shell session.")
        return

    try:
        process = subprocess.Popen(
            _split_command(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=shell_session.cwd,
            env=shell_session.env,
        )
        stdout, stderr = process.communicate(timeout=30)
        output = stdout if process.returncode == 0 else stderr
        shell_session.history.append(command)
        shell_session.history = shell_session.history[-20:]

        if output:
            await update.effective_message.reply_text(_format_output(output), parse_mode="HTML")
        else:
            await update.effective_message.reply_text("✅ Command completed successfully with no output.")
    except ValueError as exc:
        await update.effective_message.reply_text(
            f"<b>Invalid Command</b>\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )
    except FileNotFoundError:
        await update.effective_message.reply_text("❌ Command not found on this host.")
    except subprocess.TimeoutExpired:
        await update.effective_message.reply_text("⏱️ Command timed out after 30 seconds.")
    except Exception as exc:
        await update.effective_message.reply_text(
            f"<b>Command Failed</b>\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )


async def _change_directory(update: Update, new_dir: str) -> None:
    user_id = update.effective_user.id
    shell_session = _get_shell_session(user_id)
    if shell_session is None:
        await update.effective_message.reply_text("⚠️ No active shell session.")
        return

    try:
        new_path = os.path.abspath(os.path.join(shell_session.cwd, new_dir))
        if not os.path.isdir(new_path):
            await update.effective_message.reply_text(
                f"<b>Directory Not Found</b>\n<code>{html.escape(new_path)}</code>",
                parse_mode="HTML",
            )
            return

        shell_session.cwd = new_path
        await update.effective_message.reply_text(
            f"<b>Working Directory Updated</b>\n<code>{html.escape(shell_session.cwd)}</code>",
            parse_mode="HTML",
        )
    except Exception as exc:
        await update.effective_message.reply_text(
            f"<b>Directory Change Failed</b>\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )


async def start_shell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if not await guard_command(
        update,
        CommandSpec(
            name="shell",
            admin_only=True,
            disabled_message="Shell command is currently disabled.",
        ),
    ):
        return

    user_shell_states[user_id] = ShellSession()
    keyboard = [
        [
            InlineKeyboardButton("pwd", callback_data="cmd_pwd"),
            InlineKeyboardButton("ls", callback_data="cmd_ls"),
            InlineKeyboardButton("clear", callback_data="cmd_clear"),
        ],
        [
            InlineKeyboardButton("cd ..", callback_data="cmd_cd_up"),
            InlineKeyboardButton("ps", callback_data="cmd_ps"),
            InlineKeyboardButton("exit", callback_data="cmd_exit"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        (
            "<b>Interactive Shell Ready</b>\n"
            f"📂 Current directory:\n<code>{html.escape(user_shell_states[user_id].cwd)}</code>\n\n"
            "Type a command or use the quick actions below."
        ),
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def handle_shell_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_shell_states:
        return

    if not update.message or not update.message.text:
        return

    command = update.message.text.strip()
    if command.lower() == "exit":
        await exit_shell(update, user_id)
        return

    if command.startswith("cd "):
        await _change_directory(update, command[3:].strip())
        return

    await _run_command(update, command)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    shell_session = _get_shell_session(user_id)
    if shell_session is None:
        await query.answer("No active shell session.")
        return

    cmd = query.data.replace("cmd_", "")

    if cmd == "exit":
        await exit_shell(query, user_id)
    elif cmd == "pwd":
        await query.message.reply_text(
            f"<b>Current Directory</b>\n<code>{html.escape(shell_session.cwd)}</code>",
            parse_mode="HTML",
        )
    elif cmd == "ls":
        await _run_command(update, "Get-ChildItem" if os.name == "nt" else "ls")
    elif cmd == "clear":
        shell_session.history.clear()
        await query.message.reply_text("🧹 Command history cleared.")
    elif cmd == "cd_up":
        await _change_directory(update, "..")
    elif cmd == "ps":
        await _run_command(update, "tasklist" if os.name == "nt" else "ps aux")

    await query.answer()


async def exit_shell(update: Update, user_id: int) -> None:
    if user_id in user_shell_states:
        del user_shell_states[user_id]
        msg_obj = update.message if hasattr(update, "message") else update.effective_message
        await msg_obj.reply_text("🔒 Shell session closed.")


def register_shell_handlers(application) -> None:
    application.add_handler(CommandHandler("shell", start_shell))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_shell_input))
    application.add_handler(CallbackQueryHandler(handle_callback, pattern="^cmd_"))

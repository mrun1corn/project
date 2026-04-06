import html
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from command_registry import get_default_notes_commands
from database import get_collection
from group_management import error_handler, is_user_admin
from settings import settings
from toggle_ui import build_toggle_keyboard


NOTES_COLLECTION = get_collection("notes")
NOTES_COMMANDS_COLLECTION = get_collection("notes_command_states")
NOTES_COMMANDS = get_default_notes_commands()


async def load_notes(chat_id: int) -> dict:
    doc = await NOTES_COLLECTION.find_one({"_id": chat_id})
    if not doc:
        return {"group_notes": {}, "user_notes": {}}
    data = {k: v for k, v in doc.items() if k != "_id"}
    data.setdefault("group_notes", {})
    data.setdefault("user_notes", {})
    return data


async def save_notes(chat_id: int, notes: dict) -> None:
    await NOTES_COLLECTION.update_one({"_id": chat_id}, {"$set": notes}, upsert=True)


async def load_notes_command_states(chat_id: int) -> dict:
    doc = await NOTES_COMMANDS_COLLECTION.find_one({"_id": chat_id})
    if not doc:
        return NOTES_COMMANDS.copy()
    stored = doc.get("commands", {})
    states = NOTES_COMMANDS.copy()
    states.update({name: bool(value) for name, value in stored.items() if name in NOTES_COMMANDS})
    return states


async def save_notes_command_states(chat_id: int, states: dict) -> None:
    await NOTES_COMMANDS_COLLECTION.update_one({"_id": chat_id}, {"$set": {"commands": states}}, upsert=True)


def notes_command_enabled_check(command_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            states = await load_notes_command_states(update.effective_chat.id)
            if not states.get(command_name, True):
                return
            return await func(update, context, *args, **kwargs)

        return wrapped

    return decorator


async def _build_notes_manage_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    states = await load_notes_command_states(chat_id)
    return build_toggle_keyboard(
        ((command_name.capitalize(), enabled, f"notes_manage_toggle_{command_name}") for command_name, enabled in sorted(states.items())),
        extra_rows=[[InlineKeyboardButton("Enable All", callback_data="notes_manage_all_enable"), InlineKeyboardButton("Disable All", callback_data="notes_manage_all_disable")]],
    )


def _is_private_chat(update: Update) -> bool:
    return update.effective_chat.type == "private"


def _get_note_store(notes: dict, user_id: str, private_chat: bool) -> dict:
    if private_chat:
        return notes.setdefault("user_notes", {}).setdefault(user_id, {})
    return notes.setdefault("group_notes", {})


def _extract_note_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[str | None, str | None]:
    name = context.args[-1] if context.args else None

    if update.message.reply_to_message:
        source = update.message.reply_to_message
        text = source.text or source.caption
        return text, name

    if len(context.args) < 2:
        return None, name

    raw_text = " ".join(context.args[:-1]).strip()
    if raw_text.startswith('"') and raw_text.endswith('"'):
        raw_text = raw_text[1:-1]
    return raw_text or None, name


async def notes_manage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != settings.admin_chat_id:
        await update.message.reply_text("🔒 You are not authorized to manage note commands.")
        return

    reply_markup = await _build_notes_manage_keyboard(update.effective_chat.id)
    await update.message.reply_text("<b>Notes Command Manager</b>\nToggle note commands for this chat below.", reply_markup=reply_markup, parse_mode="HTML")


async def notes_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.from_user.id != settings.admin_chat_id:
        await query.answer("🔒 You are not authorized to change these settings.", show_alert=True)
        return

    chat_id = query.message.chat.id
    states = await load_notes_command_states(chat_id)
    data = query.data

    if data == "notes_manage_all_enable":
        for command_name in states:
            states[command_name] = True
        await save_notes_command_states(chat_id, states)
        await query.edit_message_text("<b>Notes Command Manager</b>\n✅ All notes commands are enabled.", reply_markup=await _build_notes_manage_keyboard(chat_id), parse_mode="HTML")
        return

    if data == "notes_manage_all_disable":
        for command_name in states:
            states[command_name] = False
        await save_notes_command_states(chat_id, states)
        await query.edit_message_text("<b>Notes Command Manager</b>\n🛑 All notes commands are disabled.", reply_markup=await _build_notes_manage_keyboard(chat_id), parse_mode="HTML")
        return

    if data.startswith("notes_manage_toggle_"):
        command_name = data.removeprefix("notes_manage_toggle_")
        if command_name in states:
            states[command_name] = not states[command_name]
            await save_notes_command_states(chat_id, states)
            status = "enabled" if states[command_name] else "disabled"
            await query.edit_message_text(
                f"<b>Notes Command Manager</b>\n<code>{command_name}</code> is now <b>{status}</b>.",
                reply_markup=await _build_notes_manage_keyboard(chat_id),
                parse_mode="HTML",
            )
            return

    await query.edit_message_text("<b>Notes Command Manager</b>\n⚠️ Invalid command selection.", parse_mode="HTML")


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _is_private_chat(update):
        return True
    return await is_user_admin(context, update.effective_chat.id, update.effective_user.id)


@error_handler
@notes_command_enabled_check("keep")
async def keep_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    private_chat = _is_private_chat(update)

    if not private_chat and context.args and context.args[0].lower() == "private":
        await update.message.reply_text("⚠️ Private notes can only be created inside a private chat.")
        return

    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "<b>How To Save A Note</b>\n<code>/keep \"note text\" notename</code>\nOr reply to a message with <code>/keep notename</code>.",
            parse_mode="HTML",
        )
        return

    text, name = _extract_note_text(update, context)
    if update.message.reply_to_message:
        if not name:
            await update.message.reply_text("⚠️ Please provide a note name when replying to a message.")
            return
        if not text:
            await update.message.reply_text("⚠️ The replied message does not contain text or a caption to save.")
            return

    if not text or not name:
        await update.message.reply_text(
            "<b>Invalid Note Format</b>\nUse <code>/keep \"note text\" notename</code>.",
            parse_mode="HTML",
        )
        return

    chat_id = update.effective_chat.id
    notes = await load_notes(chat_id)
    user_id = str(update.effective_user.id)
    target = _get_note_store(notes, user_id, private_chat)
    target[name] = {"text": text, "creator": user_id, "created_at": update.message.date.isoformat()}
    await save_notes(chat_id, notes)
    note_type = "private" if private_chat else "group"
    await update.message.reply_text(
        f"✅ Saved {note_type} note <code>{html.escape(name)}</code>.",
        parse_mode="HTML",
    )


@error_handler
@notes_command_enabled_check("notes")
async def show_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = await load_notes(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    names = sorted(notes.get("user_notes", {}).get(user_id, {}).keys()) if _is_private_chat(update) else sorted(notes.get("group_notes", {}).keys())

    if not names:
        await update.message.reply_text("📝 No notes have been saved here yet.")
        return

    lines = ["<b>Saved Notes</b>"]
    lines.extend(f"• <code>#{html.escape(name)}</code>" for name in names)
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@error_handler
@notes_command_enabled_check("getnote")
async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text.startswith("#"):
        return

    name = text[1:].strip()
    if not name:
        await update.message.reply_text("⚠️ Please provide a note name after <code>#</code>.", parse_mode="HTML")
        return

    notes = await load_notes(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    note = notes.get("user_notes", {}).get(user_id, {}).get(name) if _is_private_chat(update) else notes.get("group_notes", {}).get(name)

    if note:
        await update.message.reply_text(note["text"], parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text(
        f"⚠️ Note <code>{html.escape(name)}</code> was not found.",
        parse_mode="HTML",
    )


@error_handler
@notes_command_enabled_check("delete")
async def delete_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "<b>How To Delete A Note</b>\n<code>/delete notename</code>",
            parse_mode="HTML",
        )
        return

    name = context.args[0]
    notes = await load_notes(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    deleted = False

    if _is_private_chat(update):
        if notes.get("user_notes", {}).get(user_id, {}).get(name):
            del notes["user_notes"][user_id][name]
            if not notes["user_notes"][user_id]:
                del notes["user_notes"][user_id]
            deleted = True
    else:
        if notes.get("group_notes", {}).get(name):
            if not await is_admin(update, context):
                await update.message.reply_text("🔒 Only admins can delete group notes.")
                return
            del notes["group_notes"][name]
            deleted = True

    if deleted:
        await save_notes(update.effective_chat.id, notes)
        await update.message.reply_text(f"🗑️ Deleted note <code>{html.escape(name)}</code>.", parse_mode="HTML")
        return

    await update.message.reply_text(
        f"⚠️ Note <code>{html.escape(name)}</code> was not found or you do not have permission to remove it.",
        parse_mode="HTML",
    )


def register_note_handlers(app: Application):
    app.add_handler(CommandHandler("keep", keep_note))
    app.add_handler(CommandHandler("notes", show_notes))
    app.add_handler(CommandHandler("delete", delete_note))
    app.add_handler(MessageHandler(filters.Regex(r'^#.+'), get_note))
    app.add_handler(CommandHandler("notes_manage", notes_manage_command))
    app.add_handler(CallbackQueryHandler(notes_manage_callback, pattern="^notes_manage_"))

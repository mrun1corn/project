from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from group_management import error_handler, admin_only, is_user_admin # Import is_user_admin
from notes_commands import notes_command_enabled_check, notes_manage_command, notes_manage_callback
from database import get_collection

NOTES_COLLECTION = get_collection("notes")

async def load_notes(chat_id: int) -> dict:
    doc = await NOTES_COLLECTION.find_one({"_id": chat_id})
    if not doc:
        return {"group_notes": {}, "user_notes": {}}
    data = {k: v for k, v in doc.items() if k != "_id"}
    data.setdefault("group_notes", {})
    data.setdefault("user_notes", {})
    return data


async def save_notes(chat_id: int, notes: dict) -> None:
    await NOTES_COLLECTION.update_one(
        {"_id": chat_id},
        {"$set": notes},
        upsert=True,
    )

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return True
    return await is_user_admin(context, update.effective_chat.id, update.effective_user.id)

@error_handler
@notes_command_enabled_check("keep")
async def keep_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" and context.args and context.args[0].lower() == "private":
        await update.message.reply_text(
            "Private notes can only be created in private chats. Use /keep or reply with /keep for group notes.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "Usage:\n/keep \"note text\" notename\nor reply to a message with /keep notename\n"
            "In private chats, use /keep \"note text\" notename for private notes",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    name = context.args[-1] if context.args else None
    text = None

    if update.message.reply_to_message:
        text = update.message.reply_to_message.text
        if not name:
            await update.message.reply_text("Please provide a notename when replying to a message")
            return
    elif len(context.args) >= 2:
        raw_text = " ".join(context.args[:-1])
        text = raw_text[1:-1] if raw_text.startswith('"') and raw_text.endswith('"') else raw_text
    else:
        await update.message.reply_text("Invalid format. Use /keep \"note text\" notename")
        return

    if text and name:
        chat_id = update.effective_chat.id
        notes = await load_notes(chat_id)
        user_id = str(update.effective_user.id)

        target = notes.setdefault("user_notes", {}).setdefault(user_id, {}) if update.effective_chat.type == "private" else notes.setdefault("group_notes", {})
        target[name] = {
            "text": text,
            "creator": user_id,
            "created_at": update.message.date.isoformat()
        }
        await save_notes(chat_id, notes)
        note_type = "private" if update.effective_chat.type == "private" else "group"
        await update.message.reply_text(f"✅ Saved {note_type} note *{name}*", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Please provide both note text and notename")

@error_handler
@notes_command_enabled_check("notes")
async def show_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = await load_notes(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    lines = ["Available notes:"]

    if update.effective_chat.type == "private":
        user_notes = notes.get("user_notes", {}).get(user_id, {})
        lines += [f"- `#{name}`" for name in sorted(user_notes.keys())]
    else:
        group_notes = notes.get("group_notes", {})
        lines += [f"- `#{name}`" for name in sorted(group_notes.keys())]

    if len(lines) == 1:
        await update.message.reply_text("No notes saved.")
    else:
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

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
        await update.message.reply_text("Please provide a notename after the #, e.g., #notename")
        return

    notes = await load_notes(update.effective_chat.id)
    user_id = str(update.effective_user.id)

    if update.effective_chat.type == "private":
        note = notes.get("user_notes", {}).get(user_id, {}).get(name)
        if note:
            await update.message.reply_text(note["text"], parse_mode=ParseMode.MARKDOWN)
            return
    else:
        note = notes.get("group_notes", {}).get(name)
        if note:
            await update.message.reply_text(note["text"], parse_mode=ParseMode.MARKDOWN)
            return

    await update.message.reply_text(f"Note *{name}* not found", parse_mode=ParseMode.MARKDOWN)

@admin_only
@error_handler
@notes_command_enabled_check("delete")
async def delete_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delete notename\nExample: /delete meeting_time", parse_mode=ParseMode.MARKDOWN)
        return

    name = context.args[0]
    notes = await load_notes(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    deleted = False

    if update.effective_chat.type == "private":
        if notes.get("user_notes", {}).get(user_id, {}).get(name):
            del notes["user_notes"][user_id][name]
            if not notes["user_notes"][user_id]:
                del notes["user_notes"][user_id]
            deleted = True
    else:
        if notes.get("group_notes", {}).get(name):
            if not await is_admin(update, context):
                await update.message.reply_text("Only admins can delete group notes", parse_mode=ParseMode.MARKDOWN)
                return
            del notes["group_notes"][name]
            deleted = True

    if deleted:
        await save_notes(update.effective_chat.id, notes)
        await update.message.reply_text(f"🗑️ Deleted note *{name}*", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"Note *{name}* not found or you don't have permission", parse_mode=ParseMode.MARKDOWN)

def register_note_handlers(app: Application):
    app.add_handler(CommandHandler("keep", keep_note))
    app.add_handler(CommandHandler("notes", show_notes))
    app.add_handler(CommandHandler("delete", delete_note))
    app.add_handler(MessageHandler(filters.Regex(r'^#.+'), get_note))
    app.add_handler(CommandHandler("notes_manage", notes_manage_command))
    app.add_handler(CallbackQueryHandler(notes_manage_callback, pattern="^notes_manage_"))

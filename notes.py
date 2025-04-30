import json
import os
import time
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters
from comm_checker import check_user_approval, check_command_enabled
from config import ADMIN_CHAT_ID

# File to store notes
NOTES_FILE = "notes.json"

def load_notes():
    """Load notes from JSON file with error handling."""
    try:
        if os.path.exists(NOTES_FILE):
            with open(NOTES_FILE, 'r') as f:
                return json.load(f)
        return {"notes": []}
    except (json.JSONDecodeError, IOError):
        return {"notes": []}

def save_notes(notes):
    """Save notes to JSON file with error handling."""
    try:
        with open(NOTES_FILE, 'w') as f:
            json.dump(notes, f, indent=2)
    except IOError:
        pass

def generate_note_id():
    """Generate a unique note ID based on timestamp."""
    return str(int(time.time() * 1000))

def get_title_from_content(content):
    """Extract first two words from content as title, joined with underscore."""
    if not content or not content.strip():
        return "(No title)"
    words = content.strip().split()
    return "_".join(words[:2]) if len(words) >= 2 else words[0]

def validate_title(title):
    """Validate note title to prevent problematic characters."""
    if not title or not title.strip():
        return False
    # Allow alphanumeric, underscores, hyphens, and spaces
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ")
    return all(c in allowed_chars for c in title)

def get_user_notes(notes, chat_id, user_id, is_group):
    """Filter notes for a user or group."""
    return [
        note for note in notes["notes"]
        if (note["chat_id"] == (chat_id if is_group else user_id) or
            (note["user_id"] == user_id and not note["is_group"]))
    ]

async def store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save a new note with title and content, or content from replied message."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ["group", "supergroup"]

    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('store', user_id):
        await update.message.reply_text("❌ The store command is currently disabled.")
        return

    note_title = None
    note_content = None
    has_reply = update.message.reply_to_message and update.message.reply_to_message.text

    if context.args:
        if len(context.args) >= 2 and validate_title(context.args[0]):
            note_title = context.args[0]
            note_content = " ".join(context.args[1:])
        elif has_reply and len(context.args) == 1 and validate_title(context.args[0]):
            note_title = context.args[0]
            note_content = update.message.reply_to_message.text
        else:
            note_content = " ".join(context.args)
            note_title = get_title_from_content(note_content)
    elif has_reply:
        note_content = update.message.reply_to_message.text
        note_title = get_title_from_content(note_content)
    else:
        await update.message.reply_text("Usage: /store <title> <content> or /store <content> or /store [title] (reply to a message)")
        return

    if not note_content:
        await update.message.reply_text("❌ Note content cannot be empty.")
        return

    notes = load_notes()
    note = {
        "id": generate_note_id(),
        "user_id": user_id,
        "chat_id": chat_id if is_group else user_id,
        "title": note_title,
        "content": note_content,
        "timestamp": int(time.time()),
        "is_group": is_group
    }
    notes["notes"].append(note)
    save_notes(notes)

    await update.message.reply_text(f"📝 Note ‘{note_title}’ saved")

async def getnote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retrieve a note by title or content keyword."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ["group", "supergroup"]

    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('getnote', user_id):
        await update.message.reply_text("❌ The getnote command is currently disabled.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /getnote <title or keyword>")
        return

    query = " ".join(context.args).lower()
    notes = load_notes()
    user_notes = get_user_notes(notes, chat_id, user_id, is_group)

    # Exact title match
    matching_notes = [
        note for note in user_notes
        if note.get("title", "").lower() == query
    ]
    if matching_notes:
        note = max(matching_notes, key=lambda x: x["timestamp"])
        title_text = f"Title: {note['title']}\n" if note.get("title") else ""
        content = note.get("content", note.get("text", ""))
        await update.message.reply_text(
            f"📝 {title_text}Content: {content}\nCreated: <i>{time.ctime(note['timestamp'])}</i>",
            parse_mode="HTML"
        )
        return

    # Keyword search in title or content
    matching_notes = [
        note for note in user_notes
        if (query in note.get("title", "").lower() or
            query in note.get("content", note.get("text", "")).lower())
    ]
    if not matching_notes:
        await update.message.reply_text("❌ No notes found matching your query.")
        return
    if len(matching_notes) == 1:
        note = matching_notes[0]
        title_text = f"Title: {note['title']}\n" if note.get("title") else ""
        content = note.get("content", note.get("text", ""))
        await update.message.reply_text(
            f"📝 {title_text}Content: {content}\nCreated: <i>{time.ctime(note['timestamp'])}</i>",
            parse_mode="HTML"
        )
    else:
        message = f"📝 Found {len(matching_notes)} notes matching '{query}':\n\n"
        for note in matching_notes[:5]:
            title = note.get("title", "(No title)")
            content = note.get("content", note.get("text", ""))[:30] + "..." if note.get("content", note.get("text", "")) else "(No content)"
            message += f"- {title} | `{content}`\n"
        await update.message.reply_text(message, parse_mode="Markdown")

async def listnotes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all note titles for the user or group with bold, copyable titles."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ["group", "supergroup"]

    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('listnotes', user_id):
        await update.message.reply_text("❌ The listnotes command is currently disabled.")
        return

    notes = load_notes()
    user_notes = get_user_notes(notes, chat_id, user_id, is_group)

    if not user_notes:
        await update.message.reply_text("📝 No notes found.")
        return

    message = f"<b>List of notes ({len(user_notes)}):</b>\n\n"
    for note in user_notes[:10]:
        title = note.get("title", "(No title)")
        message += f"- <b><code>{title}</code></b>\n"
    if len(user_notes) > 10:
        message += f"...and {len(user_notes) - 10} more."
    await update.message.reply_text(message, parse_mode="HTML")

async def deletenote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a note by title."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ["group", "supergroup"]

    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('deletenote', user_id):
        await update.message.reply_text("❌ The deletenote command is currently disabled.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /deletenote <title>")
        return

    title = " ".join(context.args).lower()
    notes = load_notes()
    user_notes = get_user_notes(notes, chat_id, user_id, is_group)

    matching_notes = [
        note for note in user_notes
        if note.get("title", "").lower() == title
    ]
    if not matching_notes:
        await update.message.reply_text(f"❌ No note found with title '{title}' or you don't have permission to delete it.")
        return

    note_to_delete = max(matching_notes, key=lambda x: x["timestamp"])
    notes["notes"].remove(note_to_delete)
    save_notes(notes)
    await update.message.reply_text(f"🗑️ Note '{note_to_delete['title']}' deleted.")

async def handle_hashtag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retrieve note content when a message starts with #notename."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ["group", "supergroup"]

    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this feature.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('getnote', user_id):
        await update.message.reply_text("❌ The note retrieval feature is currently disabled.")
        return

    text = update.message.text.strip()
    if not text.startswith("#"):
        return

    query = text[1:].strip().lower()
    if not query:
        return

    notes = load_notes()
    user_notes = get_user_notes(notes, chat_id, user_id, is_group)

    matching_notes = [
        note for note in user_notes
        if note.get("title", "").lower() == query
    ]
    if matching_notes:
        note = max(matching_notes, key=lambda x: x["timestamp"])
        content = note.get("content", note.get("text", ""))
        await update.message.reply_text(content)
        return

    await update.message.reply_text(f"❌ No note found with title '{query}'.")

# Handler for hashtag messages
hashtag_handler = MessageHandler(filters.Regex(r'^#[\w\s\-\_]+'), handle_hashtag)
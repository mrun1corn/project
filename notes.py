import json
import os
import time
from telegram import Update
from telegram.ext import ContextTypes
from comm_checker import check_user_approval, check_command_enabled
from config import ADMIN_CHAT_ID

# File to store notes
NOTES_FILE = "notes.json"

# Load notes from JSON file
def load_notes():
    try:
        with open(NOTES_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"notes": []}

# Save notes to JSON file
def save_notes(notes):
    try:
        with open(NOTES_FILE, 'w') as f:
            json.dump(notes, f, indent=2)
    except Exception as e:
        print(f"Error saving notes: {e}")

# Generate a unique note ID
def generate_note_id():
    return str(int(time.time() * 1000))

async def store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save a new note with title and content, or content from replied message."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
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
        if len(context.args) >= 2:
            # /store <notename> <notebody>
            note_title = context.args[0]
            note_content = " ".join(context.args[1:])
        elif has_reply:
            # /store <title> (with reply)
            note_title = context.args[0]
            note_content = update.message.reply_to_message.text
        else:
            # /store <content> (no reply)
            note_content = " ".join(context.args)
    elif has_reply:
        # /store (with reply)
        note_content = update.message.reply_to_message.text
    else:
        await update.message.reply_text("Usage: /store <title> <content> or /store <content> or /store [title] (reply to a message)")
        return

    notes = load_notes()
    note_id = generate_note_id()
    is_group = update.effective_chat.type in ["group", "supergroup"]
    note = {
        "id": note_id,
        "user_id": user_id,
        "chat_id": chat_id if is_group else user_id,  # Store chat_id for groups, user_id for private
        "title": note_title,  # Can be null if no title
        "content": note_content,
        "timestamp": int(time.time()),
        "is_group": is_group
    }
    notes["notes"].append(note)
    save_notes(notes)

    if note_title:
        await update.message.reply_text(f"📝 Note ‘{note_title}’ saved")
    else:
        await update.message.reply_text("📝 Note saved")

async def getnote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retrieve a note by title or content keyword."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('getnote', user_id):
        await update.message.reply_text("❌ The getnote command is currently disabled.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /getnote <title or keyword>")
        return

    query = " ".join(context.args)
    notes = load_notes()
    is_group = update.effective_chat.type in ["group", "supergroup"]
    user_notes = [
        note for note in notes["notes"]
        if (note["chat_id"] == (chat_id if is_group else user_id) or
            (note["user_id"] == user_id and not note["is_group"]))
    ]

    # Try exact title match first
    matching_notes = [
        note for note in user_notes
        if "title" in note and note["title"] and query.lower() == note["title"].lower()
    ]
    if matching_notes:
        note = max(matching_notes, key=lambda x: x["timestamp"])  # Get most recent
        title_text = f"Title: {note['title']}\n" if "title" in note and note["title"] else ""
        content = note.get("content", note.get("text", ""))
        await update.message.reply_text(
            f"📝 {title_text}"
            f"Content: {content}\n"
            f"Created: <i>{time.ctime(note['timestamp'])}</i>",
            parse_mode="HTML"
        )
        return

    # Fallback to keyword search in title or content
    matching_notes = [
        note for note in user_notes
        if (("title" in note and note["title"] and query.lower() in note["title"].lower()) or
            (note.get("content", note.get("text", "")) and query.lower() in note.get("content", note.get("text", "")).lower()))
    ]
    if not matching_notes:
        await update.message.reply_text("❌ No notes found matching your query.")
        return
    if len(matching_notes) == 1:
        note = matching_notes[0]
        title_text = f"Title: {note['title']}\n" if "title" in note and note["title"] else ""
        content = note.get("content", note.get("text", ""))
        await update.message.reply_text(
            f"📝 {title_text}"
            f"Content: {content}\n"
            f"Created: <i>{time.ctime(note['timestamp'])}</i>",
            parse_mode="HTML"
        )
    else:
        message = f"📝 Found {len(matching_notes)} notes matching '{query}':\n\n"
        for note in matching_notes[:5]:  # Limit to 5 to avoid flooding
            title_preview = f"`{note['title'][:20]}...`" if "title" in note and note["title"] else "`(No title)`"
            content_preview = f"`{note.get('content', note.get('text', ''))[:30]}...`" if note.get("content", note.get("text", "")) else "`(No content)`"
            message += f"{title_preview} | {content_preview}\n"
        await update.message.reply_text(message, parse_mode="Markdown")

async def listnotes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all notes for the user or group with markup for easy copying."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('listnotes', user_id):
        await update.message.reply_text("❌ The listnotes command is currently disabled.")
        return

    notes = load_notes()
    is_group = update.effective_chat.type in ["group", "supergroup"]
    user_notes = [
        note for note in notes["notes"]
        if (note["chat_id"] == (chat_id if is_group else user_id) or
            (note["user_id"] == user_id and not note["is_group"]))
    ]

    if not user_notes:
        await update.message.reply_text("📝 No notes found.")
        return

    message = f"📝 Your notes ({len(user_notes)}):\n\n"
    for note in user_notes[:10]:  # Limit to 10 to avoid flooding
        title_preview = f"`{note['title'][:20]}...`" if "title" in note and note["title"] else "`(No title)`"
        content_preview = f"`{note.get('content', note.get('text', ''))[:30]}...`" if note.get("content", note.get("text", "")) else "`(No content)`"
        message += f"{title_preview}\n"
    if len(user_notes) > 10:
        message += f"...and {len(user_notes) - 10} more."
    await update.message.reply_text(message, parse_mode="Markdown")

async def deletenote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a note by title."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('deletenote', user_id):
        await update.message.reply_text("❌ The deletenote command is currently disabled.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /deletenote <title>")
        return

    title = " ".join(context.args)
    notes = load_notes()
    is_group = update.effective_chat.type in ["group", "supergroup"]

    # Find the most recent note with the exact title
    note_to_delete = None
    matching_notes = [
        note for note in notes["notes"]
        if "title" in note and note["title"] and title.lower() == note["title"].lower() and
           ((note["chat_id"] == (chat_id if is_group else user_id) or
             (note["user_id"] == user_id and not note["is_group"])) or user_id == ADMIN_CHAT_ID)
    ]
    if matching_notes:
        note_to_delete = max(matching_notes, key=lambda x: x["timestamp"])  # Most recent

    if not note_to_delete:
        await update.message.reply_text(f"❌ No note found with title '{title}' or you don't have permission to delete it.")
        return

    notes["notes"].remove(note_to_delete)
    save_notes(notes)
    await update.message.reply_text(f"🗑️ Note '{title}' deleted.")
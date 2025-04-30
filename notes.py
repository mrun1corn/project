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
    """Save a new note for the user or group, either from command args or replied message."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('store', user_id):
        await update.message.reply_text("❌ The store command is currently disabled.")
        return

    # Check if the command is a reply to a message
    if update.message.reply_to_message and update.message.reply_to_message.text:
        note_text = update.message.reply_to_message.text
    elif context.args:
        note_text = " ".join(context.args)
    else:
        await update.message.reply_text("Usage: /store <note text> or reply to a message with /store")
        return

    notes = load_notes()
    note_id = generate_note_id()
    is_group = update.effective_chat.type in ["group", "supergroup"]
    note = {
        "id": note_id,
        "user_id": user_id,
        "chat_id": chat_id if is_group else user_id,  # Store chat_id for groups, user_id for private
        "text": note_text,
        "timestamp": int(time.time()),
        "is_group": is_group
    }
    notes["notes"].append(note)
    save_notes(notes)

    await update.message.reply_text(f"📝 Note saved with ID: {note_id}")

async def getnote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retrieve a note by ID or keyword."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('getnote', user_id):
        await update.message.reply_text("❌ The getnote command is currently disabled.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /getnote <note_id or keyword>")
        return

    query = " ".join(context.args)
    notes = load_notes()
    is_group = update.effective_chat.type in ["group", "supergroup"]
    user_notes = [
        note for note in notes["notes"]
        if (note["chat_id"] == (chat_id if is_group else user_id) or
            (note["user_id"] == user_id and not note["is_group"]))
    ]

    # Try exact ID match first
    for note in user_notes:
        if note["id"] == query:
            await update.message.reply_text(
                f"📝 Note ID: {note['id']}\n"
                f"Text: {note['text']}\n"
                f"Created: <i>{time.ctime(note['timestamp'])}</i>",
                parse_mode="HTML"
            )
            return

    # Fallback to keyword search
    matching_notes = [note for note in user_notes if query.lower() in note["text"].lower()]
    if not matching_notes:
        await update.message.reply_text("❌ No notes found matching your query.")
        return
    if len(matching_notes) == 1:
        note = matching_notes[0]
        await update.message.reply_text(
            f"📝 Note ID: {note['id']}\n"
            f"Text: {note['text']}\n"
            f"Created: <i>{time.ctime(note['timestamp'])}</i>",
            parse_mode="HTML"
        )
    else:
        message = f"📝 Found {len(matching_notes)} notes matching '{query}':\n\n"
        for note in matching_notes[:5]:  # Limit to 5 to avoid flooding
            message += f"ID: {note['id']} | {note['text'][:50]}...\n"
        await update.message.reply_text(message)

async def listnotes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all notes for the user or group."""
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
        message += f"ID: {note['id']} | {note['text'][:50]}...\n"
    if len(user_notes) > 10:
        message += f"...and {len(user_notes) - 10} more."
    await update.message.reply_text(message)

async def deletenote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a note by ID."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not await check_user_approval(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return
    if user_id != ADMIN_CHAT_ID and not await check_command_enabled('deletenote', user_id):
        await update.message.reply_text("❌ The deletenote command is currently disabled.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /deletenote <note_id>")
        return

    note_id = context.args[0]
    notes = load_notes()
    is_group = update.effective_chat.type in ["group", "supergroup"]

    # Admins can delete any note; regular users can only delete their own
    note_to_delete = None
    for note in notes["notes"]:
        if note["id"] == note_id:
            if (note["chat_id"] == (chat_id if is_group else user_id) or
                (note["user_id"] == user_id and not note["is_group"])) or user_id == ADMIN_CHAT_ID:
                note_to_delete = note
                break

    if not note_to_delete:
        await update.message.reply_text("❌ Note not found or you don't have permission to delete it.")
        return

    notes["notes"].remove(note_to_delete)
    save_notes(notes)
    await update.message.reply_text(f"🗑️ Note ID {note_id} deleted.")
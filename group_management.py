import os
import json
import time
from asyncio import sleep
from telegram import Update, ChatPermissions, ChatAdministratorRights, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.helpers import escape_markdown
from telegram.constants import ParseMode
from functools import wraps

GROUP_DATA_DIR = 'group_data'
os.makedirs(GROUP_DATA_DIR, exist_ok=True)

def _group_file(chat_id):
    return os.path.join(GROUP_DATA_DIR, f"{chat_id}.json")

def load_group(chat_id):
    path = _group_file(chat_id)
    group_data = {
        'welcome': None,
        'goodbye': None,
        'welcome_mention': True,
        'goodbye_mention': True,
        'filters': {},
        'warn_counts': {},
        'warn_limit': 3,
        'warn_mode': 'mute',
        'locks': {},
        'action_delete': True,
        'members': {}
    }
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                loaded_data = json.load(f)
                group_data.update(loaded_data) # Update default data with loaded data
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error loading group data for chat {chat_id}: {e}")
    return group_data

def save_group(chat_id, data):
    try:
        with open(_group_file(chat_id), 'w') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        pass

async def is_user_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    """Checks if a user is an administrator in the chat."""
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except Exception as e:
        print(f"Error checking admin status for chat {chat_id}, user {user_id}: {e}")
        return False

# --------------------- Decorators ---------------------

def admin_only(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        if not await is_user_admin(context, chat_id, user_id):
            await update.message.reply_text("❌ You must be an admin to use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


# --------------------- Helper Functions ---------------------



def parse_time(time_str: str) -> int:
    """Converts a time string like '1d', '2h', '30m' to seconds."""
    if not time_str:
        return 0
    try:
        unit = time_str[-1].lower()
        value = int(time_str[:-1])
        if unit == 'm':
            return value * 60
        elif unit == 'h':
            return value * 3600
        elif unit == 'd':
            return value * 86400
    except (ValueError, IndexError) as e:
        pass
    return 0

# --------------------- Core Features ---------------------

@admin_only
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)

    try:
        if not context.args:
            await update.message.reply_text(f"Welcome message:\n{group['welcome'] or '❌ Disabled'}")
            return

        arg = " ".join(context.args)
        if arg.lower() in ['off', 'no']:
            group['welcome'] = None
            await update.message.reply_text("❌ Welcome message disabled.")
        else:
            group['welcome'] = arg
            await update.message.reply_text(f"✅ Welcome message set to:\n{arg}")

        save_group(chat_id, group)
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")


@admin_only
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)

    try:
        if not context.args:
            await update.message.reply_text(f"Goodbye message:\n{group['goodbye'] or '❌ Disabled'}")
            return

        arg = " ".join(context.args)
        if arg.lower() in ['off', 'no']:
            group['goodbye'] = None
            await update.message.reply_text("❌ Goodbye message disabled.")
        else:
            group['goodbye'] = arg
            await update.message.reply_text(f"✅ Goodbye message set to:\n{arg}")

        save_group(chat_id, group)
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")



async def mention_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        if not await is_user_admin(context, query.message.chat.id, query.from_user.id):
            await query.edit_message_text("❌ You must be an admin to change this setting.")
            return
        
        chat_id = query.message.chat.id
        group = load_group(chat_id)
        
        _, type, choice = query.data.split('_')
        
        mention_enabled = choice == 'yes'
        group[f'{type}_mention'] = mention_enabled
        save_group(chat_id, group)
        
        await query.edit_message_text(f"✅ User mentions for {type} message have been {'enabled' if mention_enabled else 'disabled'}.")
    except Exception as e:
        await query.answer(f"❌ An unexpected error occurred: {e}", show_alert=True)

async def member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        group = load_group(chat_id)

        msg = group.get("welcome")
        if not msg:
            return

        mention_enabled = group.get('welcome_mention', True)

        for m in update.message.new_chat_members:
            try:
                formatted_text = msg.format(
                    first=escape_markdown(m.first_name or "", version=2),
                    fullname=escape_markdown(m.full_name, version=2),
                    username=escape_markdown(f"@{m.username}" if m.username else "", version=2),
                    mention=m.mention_markdown_v2(),
                    chatname=escape_markdown(update.effective_chat.title or "", version=2)
                )
                if not mention_enabled:
                    # If mentions are disabled, replace the markdown mention with plain full name
                    formatted_text = formatted_text.replace(m.mention_markdown_v2(), escape_markdown(m.full_name, version=2))
                await context.bot.send_message(chat_id=chat_id, text=formatted_text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as e:
                print(f"Error sending welcome message for new member {m.id}: {e}")
    except Exception as e:
        pass


async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        group = load_group(chat_id)

        msg = group.get("goodbye")
        if not msg:
            return

        mention_enabled = group.get('goodbye_mention', True)
        m = update.message.left_chat_member

        try:
            formatted_text = msg.format(
                first=escape_markdown(m.first_name or "", version=2),
                fullname=escape_markdown(m.full_name, version=2),
                username=escape_markdown(f"@{m.username}" if m.username else "", version=2),
                mention=m.mention_markdown_v2(),
                chatname=escape_markdown(update.effective_chat.title or "", version=2)
            )
            if not mention_enabled:
                # If mentions are disabled, replace the markdown mention with plain full name
                formatted_text = formatted_text.replace(m.mention_markdown_v2(), escape_markdown(m.full_name, version=2))
            await context.bot.send_message(chat_id=chat_id, text=formatted_text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            print(f"Error sending goodbye message for left member {m.id}: {e}")
    except Exception as e:
        print(f"Error in member_left: {e}")

async def service_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import asyncio
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    if group.get('action_delete', True) and update.effective_message:
        try:
            # Add a small delay to avoid race conditions
            await asyncio.sleep(0.5)
            await update.effective_message.delete()
        except Exception as e:
            print(f"Error deleting service message: {e}")

@admin_only
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /filter <keyword> <reply>")
            return
        group = load_group(chat_id)
        trigger = context.args[0].lower()
        reply = " ".join(context.args[1:])
        group['filters'][trigger] = reply
        save_group(chat_id, group)
        await update.message.reply_text(f"✅ Filter added for '{trigger}'")
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")

@admin_only
async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        if not context.args:
            await update.message.reply_text("Usage: /stop <keyword>")
            return
        trigger = context.args[0].lower()
        group = load_group(chat_id)
        if trigger in group['filters']:
            del group['filters'][trigger]
            save_group(chat_id, group)
            await update.message.reply_text(f"✅ Filter '{trigger}' removed")
        else:
            await update.message.reply_text("❌ Filter not found.")
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")

async def enforce_locks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id

    # Admins are immune to locks
    if await is_user_admin(context, chat_id, user_id):
        return

    group = load_group(chat_id)
    locks = group.get("locks", {})

    # Check for all lockable types
    should_delete = False
    if locks.get("text") and update.message.text:
        should_delete = True
    elif locks.get("photo") and update.message.photo:
        should_delete = True
    elif locks.get("video") and update.message.video:
        should_delete = True
    elif locks.get("audio") and update.message.audio:
        should_delete = True
    elif locks.get("voice") and update.message.voice:
        should_delete = True
    elif locks.get("document") and update.message.document:
        should_delete = True
    elif locks.get("gif") and update.message.animation:
        should_delete = True
    elif locks.get("sticker") and update.message.sticker:
        should_delete = True
    elif locks.get("emoji") and update.message.entities and any(e.type == 'custom_emoji' for e in update.message.entities):
        should_delete = True
    elif locks.get("video_note") and update.message.video_note:
        should_delete = True

    if should_delete:
        try:
            await update.message.delete()
        except Exception as e:
            print(f"Error enforcing locks: {e}")


async def filter_responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return
        chat_id = update.effective_chat.id
        text = update.message.text.lower()
        group = load_group(chat_id)
        for trigger, reply in group.get("filters", {}).items():
            if trigger in text:
                await update.message.reply_text(reply)
                break
    except Exception as e:
        pass



# --------------------- Moderation ---------------------

@admin_only
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user's message to mute them.")
            return

        chat_id = update.effective_chat.id
        target_user_id = update.message.reply_to_message.from_user.id

        if await is_user_admin(context, chat_id, target_user_id):
            await update.message.reply_text("😂 Trying to mute an admin? Bold. But I can't.")
            return

        await context.bot.restrict_chat_member(
            chat_id,
            target_user_id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text("🔇 User muted.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to mute user: {e}")

@admin_only
async def tmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user's message to temporarily mute them.")
            return

        chat_id = update.effective_chat.id
        target_user_id = update.message.reply_to_message.from_user.id

        if await is_user_admin(context, chat_id, target_user_id):
            await update.message.reply_text("😂 Admins are masters of time. Can't give them a time-out.")
            return

        duration_str = context.args[0] if context.args else "1h"
        duration_sec = parse_time(duration_str)
        if duration_sec == 0:
            await update.message.reply_text("Invalid time format. Use 'm', 'h', or 'd'. E.g., /tmute 30m")
            return
        
        until_date = time.time() + duration_sec
        await context.bot.restrict_chat_member(
            chat_id,
            target_user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=int(until_date)
        )
        await update.message.reply_text(f"🔇 User muted for {duration_str}.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to mute user: {e}")

@admin_only
async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user's message to unmute them.")
            return
        user_id = update.message.reply_to_message.from_user.id
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            user_id,
            permissions=ChatPermissions(can_send_messages=True, can_send_photos=True, can_send_videos=True, can_send_audios=True, can_send_voice_notes=True, can_send_documents=True, can_send_video_notes=True, can_send_other_messages=True, can_add_web_page_previews=True)
        )
        await update.message.reply_text("🔊 User unmuted.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to unmute user: {e}")

@admin_only
async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user's message to kick them.")
            return

        chat_id = update.effective_chat.id
        target_user_id = update.message.reply_to_message.from_user.id

        if await is_user_admin(context, chat_id, target_user_id):
            await update.message.reply_text("👢 Kicking an admin? That's a declaration of war I can't participate in.")
            return

        await context.bot.ban_chat_member(chat_id, target_user_id)
        await context.bot.unban_chat_member(chat_id, target_user_id)
        await update.message.reply_text("👢 User kicked.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to kick user: {e}")

@admin_only
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user's message to ban them.")
            return

        chat_id = update.effective_chat.id
        target_user_id = update.message.reply_to_message.from_user.id

        if await is_user_admin(context, chat_id, target_user_id):
            await update.message.reply_text("🚫 Ban an admin? Nice thought, but it's not happening.")
            return

        await context.bot.ban_chat_member(chat_id, target_user_id)
        await update.message.reply_text("🚫 User banned.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to ban user: {e}")

@admin_only
async def tban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user's message to temporarily ban them.")
            return

        chat_id = update.effective_chat.id
        target_user_id = update.message.reply_to_message.from_user.id

        if await is_user_admin(context, chat_id, target_user_id):
            await update.message.reply_text("🚫 Can't put an admin in time-out. They own the naughty corner.")
            return

        duration_str = context.args[0] if context.args else "1d"
        duration_sec = parse_time(duration_str)
        if duration_sec == 0:
            await update.message.reply_text("Invalid time format. Use 'm', 'h', or 'd'. E.g., /tban 2h")
            return
            
        until_date = time.time() + duration_sec
        await context.bot.ban_chat_member(chat_id, target_user_id, until_date=int(until_date))
        await update.message.reply_text(f"🚫 User banned for {duration_str}.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to ban user: {e}")

@admin_only
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Usage: /unban <user_id>")
            return
        user_id = int(context.args[0])
        await context.bot.unban_chat_member(update.effective_chat.id, user_id)
        await update.message.reply_text("✅ User unbanned.")
    except (ValueError, IndexError) as e:
        await update.message.reply_text("Usage: /unban <user_id>")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to unban user: {e}")

# --------------------- Warning System ---------------------

@admin_only
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user to warn them.")
            return

        chat_id = update.effective_chat.id
        target_user = update.message.reply_to_message.from_user

        if await is_user_admin(context, chat_id, target_user.id):
            await update.message.reply_text("⚠️ Warn an admin? They probably wrote the rules.")
            return

        group = load_group(chat_id)
        
        warn_counts = group.setdefault('warn_counts', {})
        user_id_str = str(target_user.id)
        warn_counts[user_id_str] = warn_counts.get(user_id_str, 0) + 1
        
        limit = group.get('warn_limit', 3)
        reason = " ".join(context.args)
        
        await update.message.reply_text(
            f"⚠️ Warned {target_user.mention_markdown_v2()} ({warn_counts[user_id_str]}/{limit})."
            f"\nReason: {reason or 'No reason specified.'}",
            parse_mode="MarkdownV2"
        )

        if warn_counts[user_id_str] >= limit:
            mode = group.get('warn_mode', 'mute')
            await update.message.reply_text(f"🚨 User reached warning limit. Action: {mode.capitalize()}.")
            if mode == 'kick':
                await kick(update, context)
            elif mode == 'ban':
                await ban(update, context)
            else: # mute
                await mute(update, context)
            warn_counts[user_id_str] = 0 # Reset warnings

        save_group(chat_id, group)
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")

@admin_only
async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user to check their warnings.")
            return
        
        chat_id = update.effective_chat.id
        target_user = update.message.reply_to_message.from_user
        group = load_group(chat_id)
        
        count = group.get('warn_counts', {}).get(str(target_user.id), 0)
        await update.message.reply_text(f"User {target_user.mention_markdown_v2()} has {count} warnings.", parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")

@admin_only
async def set_warn_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args or not context.args[0].isdigit():
            await update.message.reply_text("Usage: /warnlimit <number>")
            return
        chat_id = update.effective_chat.id
        group = load_group(chat_id)
        group['warn_limit'] = int(context.args[0])
        save_group(chat_id, group)
        await update.message.reply_text(f"✅ Warning limit set to {context.args[0]}.")
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")

@admin_only
async def set_warn_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args or context.args[0].lower() not in ['mute', 'kick', 'ban']:
            await update.message.reply_text("Usage: /warnmode <mute|kick|ban>")
            return
        chat_id = update.effective_chat.id
        group = load_group(chat_id)
        group['warn_mode'] = context.args[0].lower()
        save_group(chat_id, group)
        await update.message.reply_text(f"✅ Warning mode set to {context.args[0].lower()}.")
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")


# --------------------- Group Settings ---------------------

LOCKABLE_TYPES = ["gif", "sticker", "photo", "video", "audio", "voice", "document", "text", "emoji", "video_note"]

@admin_only
async def locks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        group = load_group(chat_id)
        locks = group.setdefault("locks", {})

        keyboard = []
        for lock_type in LOCKABLE_TYPES:
            status_icon = "🔒" if locks.get(lock_type) else "🔓"
            keyboard.append([InlineKeyboardButton(f"{status_icon} {lock_type.capitalize()}", callback_data=f"toggle_lock_{lock_type}")])

        keyboard.append([
            InlineKeyboardButton("Lock All", callback_data="toggle_lock_all_lock"),
            InlineKeyboardButton("Unlock All", callback_data="toggle_lock_all_unlock")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🔧 Manage group locks:", reply_markup=reply_markup)
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")

async def locks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    chat_id = query.message.chat.id
    try:
        if not await is_user_admin(context, chat_id, query.from_user.id):
            await query.answer(text="❌ You must be an admin to change this setting.", show_alert=True)
            return

        bot_rights = await get_bot_admin_rights(context, chat_id)
        if not bot_rights.can_restrict_members:
            await query.answer(text="❌ I don't have permission to restrict members. Grant me 'Restrict members' right.", show_alert=True)
            return
        if not bot_rights.can_delete_messages:
            await query.answer(text="❌ I don't have permission to delete messages. Grant me 'Delete messages' right.", show_alert=True)
            return

        group = load_group(chat_id)
        locks = group.setdefault("locks", {})
        original_locks = locks.copy()

        _, _, *data = query.data.split('_')
        lock_type = data[0]

        if lock_type == "all":
            action = data[1]
            for l_type in LOCKABLE_TYPES:
                locks[l_type] = action == "lock"
        else:
            locks[lock_type] = not locks.get(lock_type, False)

        if original_locks == locks:
            await query.answer(text="No changes were made.")
            return

        save_group(chat_id, group)

        # Apply permissions to the chat
        # Create a new dictionary with all valid ChatPermissions arguments, defaulting to True
        permissions_data = {
            "can_send_messages": True,
            "can_send_photos": True,
            "can_send_videos": True,
            "can_send_audios": True,
            "can_send_voice_notes": True,
            "can_send_documents": True,
            "can_send_video_notes": True,
            "can_send_polls": True,
            "can_send_other_messages": True,
            "can_add_web_page_previews": True,
            "can_change_info": True,
            "can_invite_users": True,
            "can_pin_messages": True,
            "can_manage_topics": True,
        }

        # Apply lock logic to the new dictionary
        permissions_data["can_send_messages"] = not locks.get("text", False)
        permissions_data["can_send_photos"] = not locks.get("photo", False)
        permissions_data["can_send_videos"] = not locks.get("video", False)
        permissions_data["can_send_audios"] = not locks.get("audio", False)
        permissions_data["can_send_voice_notes"] = not locks.get("voice", False)
        permissions_data["can_send_documents"] = not locks.get("document", False)
        permissions_data["can_send_video_notes"] = not locks.get("video_note", False)
        permissions_data["can_send_other_messages"] = not (locks.get("emoji", False) or locks.get("sticker", False) or locks.get("gif", False))

        permissions = ChatPermissions(**permissions_data)

        # Rebuild the keyboard with updated status
        keyboard = []
        for l_type in LOCKABLE_TYPES:
            status_icon = "🔒" if locks.get(l_type) else "🔓"
            keyboard.append([InlineKeyboardButton(f"{status_icon} {l_type.capitalize()}", callback_data=f"toggle_lock_{l_type}")])

        keyboard.append([
            InlineKeyboardButton("Lock All", callback_data="toggle_lock_all_lock"),
            InlineKeyboardButton("Unlock All", callback_data="toggle_lock_all_unlock")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🔧 Manage group locks:", reply_markup=reply_markup)
        await query.answer(text="✅ Settings updated and applied!")
    except Exception as e:
        print(f"Error in locks_callback: {e}") # Added for debugging
        await query.answer(f"❌ An unexpected error occurred: {e}", show_alert=True)

@admin_only
async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notify = 'loud' in context.args
    
    try:
        if update.message.reply_to_message:
            message_id = update.message.reply_to_message.message_id
        elif context.args:
            # This part is tricky as we can't just "pin text". We pin a message.
            # So the bot will send a message first, then pin it.
            text_to_pin = " ".join(arg for arg in context.args if arg != 'loud')
            if not text_to_pin:
                await update.message.reply_text("Usage: /pin [loud] <text> or reply to a message.")
                return
            sent_message = await update.message.reply_text(text_to_pin)
            message_id = sent_message.message_id
        else:
            await update.message.reply_text("Reply to a message or provide text to pin.")
            return
            
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=message_id,
            disable_notification=not notify
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to pin message: {e}")

@admin_only
async def action_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        group = load_group(chat_id)
        current_state = group.get('action_delete', True)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Auto-Delete ON", callback_data="action_set_on")],
            [InlineKeyboardButton("❌ Auto-Delete OFF", callback_data="action_set_off")]
        ])

        await update.message.reply_text(
            f"🔧 Service Message Control\n\nCurrently, service messages (like user joins/leaves) are automatically deleted: **{'ON' if current_state else 'OFF'}**.\n\nChoose a new setting:",
            reply_markup=keyboard
        )
    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected error occurred: {e}")

async def action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        if not await is_user_admin(context, query.message.chat.id, query.from_user.id):
            await query.edit_message_text("❌ You must be an admin to change this setting.")
            return
        
        chat_id = query.message.chat.id
        group = load_group(chat_id)
        
        new_state = query.data == "action_set_on"
        group['action_delete'] = new_state
        save_group(chat_id, group)
        
        status = "ON" if new_state else "OFF"
        await query.edit_message_text(f"✅ Service message auto-deletion is now **{status}**.", parse_mode="Markdown")
    except Exception as e:
        await query.answer(f"❌ An unexpected error occurred: {e}", show_alert=True)

# --------------------- Admin Roles ---------------------

MINIMAL_ADMIN_RIGHTS = ChatAdministratorRights(
    can_manage_chat=True, can_delete_messages=False, can_manage_video_chats=False,
    can_restrict_members=False, can_promote_members=False, can_change_info=False,
    can_invite_users=False, can_pin_messages=False, is_anonymous=False,
    can_manage_topics=False, can_post_stories=False, can_edit_stories=False,
    can_delete_stories=False,
)

PERMISSION_MAP = {
    'delete': 'can_delete_messages', 'restrict': 'can_restrict_members',
    'pin': 'can_pin_messages', 'video': 'can_manage_video_chats',
    'info': 'can_change_info', 'invite': 'can_invite_users',
    'promote': 'can_promote_members', 'anonymous': 'is_anonymous',
    'topics': 'can_manage_topics', 'post_stories': 'can_post_stories',
    'edit_stories': 'can_edit_stories', 'delete_stories': 'can_delete_stories'
}

async def get_bot_admin_rights(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> ChatAdministratorRights:
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status == 'administrator':
            return ChatAdministratorRights(
                can_manage_chat=bot_member.can_manage_chat,
                can_delete_messages=bot_member.can_delete_messages,
                can_manage_video_chats=bot_member.can_manage_video_chats,
                can_restrict_members=bot_member.can_restrict_members,
                can_promote_members=bot_member.can_promote_members,
                can_change_info=bot_member.can_change_info,
                can_invite_users=bot_member.can_invite_users,
                can_pin_messages=bot_member.can_pin_messages,
                is_anonymous=bot_member.is_anonymous,
                can_manage_topics=bot_member.can_manage_topics,
                can_post_stories=bot_member.can_post_stories,
                can_edit_stories=bot_member.can_edit_stories,
                can_delete_stories=bot_member.can_delete_stories,
            )
    except Exception as e:
        print(f"Error getting bot admin rights for chat {chat_id}: {e}")
    return ChatAdministratorRights() # Return empty rights if not admin or error

@admin_only
async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to promote them.")
        return

    user_id = update.message.reply_to_message.from_user.id
    chat_id = update.effective_chat.id
    custom_title = " ".join(context.args) if context.args else "Admin"

    try:
        bot_rights = await get_bot_admin_rights(context, chat_id)
        promotable_rights = MINIMAL_ADMIN_RIGHTS.to_dict()

        # Only grant rights that the bot itself has
        for right, value in promotable_rights.items():
            if value and not getattr(bot_rights, right, False):
                promotable_rights[right] = False # Bot cannot grant what it doesn't have

        await context.bot.promote_chat_member(
            chat_id=chat_id, user_id=user_id, **promotable_rights
        )
        await context.bot.set_chat_administrator_custom_title(chat_id, user_id, custom_title)
        await update.message.reply_text(f"✅ Promoted with title: {custom_title}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to promote: {e}")

@admin_only
async def permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to manage their permissions.")
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    try:
        member = await context.bot.get_chat_member(chat_id, target_user_id)
        if member.status not in ('administrator', 'creator'):
            await update.message.reply_text("❌ User is not an admin. Promote them first.")
            return

        current_rights_dict = {}
        for perm_key, perm_name in PERMISSION_MAP.items():
            current_rights_dict[perm_name] = getattr(member, perm_name, False)

        keyboard = []
        for perm_key, perm_name in PERMISSION_MAP.items():
            status_icon = "✅" if current_rights_dict.get(perm_name) else "❌"
            keyboard.append([InlineKeyboardButton(
                f"{status_icon} {perm_key.replace('_', ' ').capitalize()}", 
                callback_data=f"toggle_perm_{target_user_id}_{perm_key}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"🔧 Managing permissions for {member.user.first_name}:",
            reply_markup=reply_markup
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Failed to fetch permissions: {e}")

async def permissions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    chat_id = query.message.chat.id
    requesting_user_id = query.from_user.id

    if not await is_user_admin(context, chat_id, requesting_user_id):
        await query.answer(text="❌ You must be an admin to change this setting.", show_alert=True)
        return

    _, _, target_user_id_str, perm_key = query.data.split('_', 3)
    target_user_id = int(target_user_id_str)
    permission_name = PERMISSION_MAP[perm_key]

    try:
        member = await context.bot.get_chat_member(chat_id, target_user_id)
        if member.status not in ('administrator', 'creator'):
            await query.edit_message_text("❌ User is no longer an admin.")
            return

        bot_rights = await get_bot_admin_rights(context, chat_id)
        if not getattr(bot_rights, permission_name, False):
            await query.answer(f"❌ I don't have permission to change '{perm_key}'.", show_alert=True)
            return

        # Start with a base of all permissions (e.g., MINIMAL_ADMIN_RIGHTS)
        # Then overlay the current permissions from the member object
        # Finally, apply the toggled permission
        updated_rights_dict = MINIMAL_ADMIN_RIGHTS.to_dict()
        for perm_key_map, perm_name_map in PERMISSION_MAP.items():
            updated_rights_dict[perm_name_map] = getattr(member, perm_name_map, False)

        # Toggle the specific permission
        updated_rights_dict[permission_name] = not updated_rights_dict.get(permission_name, False)
        
        new_rights = ChatAdministratorRights(**updated_rights_dict)

        await context.bot.promote_chat_member(chat_id, target_user_id, **new_rights.to_dict())
        
        # Rebuild the keyboard with updated status
        keyboard = []
        for p_key, p_name in PERMISSION_MAP.items():
            status_icon = "✅" if new_rights.to_dict().get(p_name) else "❌"
            keyboard.append([InlineKeyboardButton(
                f"{status_icon} {p_key.replace('_', ' ').capitalize()}", 
                callback_data=f"toggle_perm_{target_user_id}_{p_key}"
            )])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🔧 Managing permissions for {member.user.first_name}:",
            reply_markup=reply_markup
        )
        await query.answer(f"✅ {perm_key.capitalize()} permission updated.")

    except Exception as e:
        await query.answer(f"❌ Failed to update permission: {e}", show_alert=True)

@admin_only
async def demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to demote them.")
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    try:
        if not await is_user_admin(context, chat_id, target_user_id):
            await update.message.reply_text("❌ User is not an admin.")
            return

        bot_rights = await get_bot_admin_rights(context, chat_id)
        if not bot_rights.can_promote_members:
            await update.message.reply_text("❌ I don't have permission to demote members. Grant me 'Promote Members' right.")
            return

        # Demote by setting all admin rights to False
        await context.bot.promote_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            is_anonymous=False,
            can_manage_topics=False,
            can_post_stories=False,
            can_edit_stories=False,
            can_delete_stories=False,
        )
        await update.message.reply_text("✅ User demoted.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to demote user: {e}")


# --------------------- Utility ---------------------

async def update_member_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Keeps a list of active members."""
    if not update.message or not update.message.from_user:
        return
    chat_id = update.effective_chat.id
    user = update.message.from_user
    group = load_group(chat_id)
    members = group.setdefault('members', {})
    members[str(user.id)] = user.username or user.first_name
    # Removed save_group here to prevent excessive disk I/O.
    # Member list persistence will need a separate, less frequent mechanism if desired.

@admin_only
async def tagadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to fetch admins: {e}")
        return

    mention_text = " ".join(f"@{admin.user.username}" for admin in admins if admin.user.username)
    reason = " ".join(context.args)

    if not mention_text:
        await update.message.reply_text("No admins with usernames found to mention.")
        return

    message = f"📣 **Calling all admins!**\n{reason}\n\n{mention_text}"
    await update.message.reply_text(message, parse_mode="Markdown")


# --------------------- Registration ---------------------

def register_group_management(app):
    # Welcome/Goodbye
    app.add_handler(CommandHandler("welcome", welcome))
    app.add_handler(CommandHandler("goodbye", goodbye))
    app.add_handler(CallbackQueryHandler(mention_callback, pattern="^mention_"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, member_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))
    
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, enforce_locks), group=-2)

    # Service message handler for auto-deletion
    app.add_handler(MessageHandler(filters.StatusUpdate.ALL, service_message_handler), group=-1)  # Higher priority to delete service messages

    # Filters
    app.add_handler(CommandHandler("filter", add_filter))
    app.add_handler(CommandHandler("stop", remove_filter))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_responder))

    # Moderation
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("tmute", tmute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("tban", tban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("kick", kick))

    # Warning System
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("warns", warns))
    app.add_handler(CommandHandler("warnlimit", set_warn_limit))
    app.add_handler(CommandHandler("warnmode", set_warn_mode))

    # Group Settings
    app.add_handler(CommandHandler("locks", locks))
    app.add_handler(CallbackQueryHandler(locks_callback, pattern="^toggle_lock_"))
    app.add_handler(CommandHandler("pin", pin))
    app.add_handler(CommandHandler("action", action_toggle))
    app.add_handler(CallbackQueryHandler(action_callback, pattern="^action_set_"))

    # Admin Roles
    app.add_handler(CommandHandler("promote", promote))
    app.add_handler(CommandHandler("demote", demote))
    app.add_handler(CommandHandler("permissions", permissions))
    app.add_handler(CallbackQueryHandler(permissions_callback, pattern="^toggle_perm_"))

    # Utility
    app.add_handler(CommandHandler("tagadmin", tagadmin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, update_member_list), group=1) # Lower priority

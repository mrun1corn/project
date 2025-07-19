import os
import json
import time
from asyncio import sleep
from telegram import Update, ChatPermissions, ChatAdministratorRights, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.helpers import escape_markdown
from telegram.constants import ParseMode
from functools import wraps
from group_management_commands import group_management_command_enabled_check, group_manage_command, group_manage_callback

# --- Constants ---
ADMIN_ONLY_MSG = "❌ You must be an admin to use this command."
ADMIN_PERMISSION_MSG = "❌ You must be an admin to change this setting."
REPLY_TO_USER_MSG = "Reply to a user's message to use this command."
NO_ADMIN_MUTE_BAN_MSG = "😂 Trying to mute an admin? Bold. But I can't."
NO_ADMIN_KICK_MSG = "👢 Kicking an admin? That's a declaration of war I can't participate in."
NO_ADMIN_BAN_MSG = "🚫 Ban an admin? Nice thought, but it's not happening."
NO_ADMIN_TBAN_MSG = "🚫 Can't put an admin in time-out. They own the naughty corner."
NO_ADMIN_WARN_MSG = "⚠️ Warn an admin? They probably wrote the rules."
INVALID_TIME_FORMAT_MSG = "Invalid time format. Use 'm', 'h', or 'd'. E.g., /tmute 30m"
BOT_NO_RESTRICT_PERMISSION_MSG = "❌ I don't have permission to restrict members. Grant me 'Restrict members' right."
BOT_NO_DELETE_PERMISSION_MSG = "❌ I don't have permission to delete messages. Grant me 'Delete messages' right."
BOT_NO_PROMOTE_PERMISSION_MSG = "❌ I don't have permission to promote members. Grant me 'Promote Members' right."
BOT_NO_CHANGE_INFO_PERMISSION_MSG = "❌ I don't have permission to change chat info. Grant me 'Change Info' right."
BOT_NO_INVITE_USERS_PERMISSION_MSG = "❌ I don't have permission to invite users. Grant me 'Invite Users' right."
BOT_NO_PIN_MESSAGES_PERMISSION_MSG = "❌ I don't have permission to pin messages. Grant me 'Pin Messages' right."
BOT_NO_MANAGE_TOPICS_PERMISSION_MSG = "❌ I don't have permission to manage topics. Grant me 'Manage Topics' right."
USAGE_FILTER_MSG = "Usage: /filter <keyword> <reply>"
USAGE_STOP_MSG = "Usage: /stop <keyword>"
USAGE_UNBAN_MSG = "Usage: /unban <user_id>"
USAGE_WARN_LIMIT_MSG = "Usage: /warnlimit <number>"
USAGE_WARN_MODE_MSG = "Usage: /warnmode <mute|kick|ban>"
USAGE_PIN_MSG = "Usage: /pin [loud] <text> or reply to a message."
NO_USERNAME_ADMINS_MSG = "No admins with usernames found to mention."
USER_NOT_ADMIN_PROMOTE_FIRST_MSG = "❌ User is not an admin. Promote them first."
USER_NO_LONGER_ADMIN_MSG = "❌ User is no longer an admin."

# --- Decorators ---
def error_handler(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            print(f"Error in {func.__name__}: {e}")
            if update.message:
                await update.message.reply_text(f"❌ An unexpected error occurred: {e}")
            elif update.callback_query:
                await update.callback_query.answer(f"❌ An unexpected error occurred: {e}", show_alert=True)
    return wrapped

def bot_has_permissions(permissions: list[str]):
    def decorator(func):
        @wraps(func)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            chat_id = update.effective_chat.id
            bot_rights = await get_bot_admin_rights(context, chat_id)
            missing_permissions = []
            for perm in permissions:
                if not getattr(bot_rights, perm, False):
                    missing_permissions.append(perm.replace("can_", "").replace("_", " ").capitalize())
            
            if missing_permissions:
                msg = f"❌ I need the following permissions to perform this action: {', '.join(missing_permissions)}."
                if update.message:
                    await update.message.reply_text(msg)
                elif update.callback_query:
                    await update.callback_query.answer(msg, show_alert=True)
                return
            return await func(update, context, *args, **kwargs)
        return wrapped
    return decorator

GROUP_DATA_DIR = 'group_data'
os.makedirs(GROUP_DATA_DIR, exist_ok=True)

_group_cache = {}

def _group_file(chat_id):
    return os.path.join(GROUP_DATA_DIR, f"{chat_id}.json")

def load_group(chat_id):
    if chat_id in _group_cache:
        return _group_cache[chat_id]

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
    
    _group_cache[chat_id] = group_data
    return group_data

def save_group(chat_id, data):
    _group_cache[chat_id] = data # Update cache
    try:
        with open(_group_file(chat_id), 'w') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        pass

_admin_cache = {}
_ADMIN_CACHE_TIMEOUT = 60 # seconds

async def is_user_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    """Checks if a user is an administrator in the chat."""
    cache_key = (chat_id, user_id)
    if cache_key in _admin_cache and time.time() - _admin_cache[cache_key][1] < _ADMIN_CACHE_TIMEOUT:
        return _admin_cache[cache_key][0]

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        is_admin = member.status in ['administrator', 'creator']
        _admin_cache[cache_key] = (is_admin, time.time())
        return is_admin
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
            if update.callback_query:
                await update.callback_query.answer(ADMIN_ONLY_MSG, show_alert=True)
            elif update.message:
                await update.message.reply_text(ADMIN_ONLY_MSG)
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
@group_management_command_enabled_check("welcome")
@error_handler
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)

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


@admin_only
@group_management_command_enabled_check("goodbye")
@error_handler
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)

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



@error_handler
async def mention_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await is_user_admin(context, query.message.chat.id, query.from_user.id):
        await query.edit_message_text(ADMIN_PERMISSION_MSG)
        return
    
    chat_id = query.message.chat.id
    group = load_group(chat_id)
    
    _, type, choice = query.data.split('_')
    
    mention_enabled = choice == 'yes'
    group[f'{type}_mention'] = mention_enabled
    save_group(chat_id, group)
    
    await query.edit_message_text(f"✅ User mentions for {type} message have been {'enabled' if mention_enabled else 'disabled'}.")

def _format_member_message(msg: str, member, chat_title: str) -> str:
    """Formats a message with member and chat details."""
    return msg.format(
        first=escape_markdown(member.first_name or "", version=2),
        fullname=escape_markdown(member.full_name, version=2),
        username=escape_markdown(f"@{member.username}" if member.username else "", version=2),
        mention=member.mention_markdown_v2(),
        chatname=escape_markdown(chat_title or "", version=2)
    )

@error_handler
async def member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)

    msg = group.get("welcome")
    if not msg:
        return

    mention_enabled = group.get('welcome_mention', True)

    for m in update.message.new_chat_members:
        formatted_text = _format_member_message(msg, m, update.effective_chat.title)
        if not mention_enabled:
            formatted_text = formatted_text.replace(m.mention_markdown_v2(), escape_markdown(m.full_name, version=2))
        await context.bot.send_message(chat_id=chat_id, text=formatted_text, parse_mode=ParseMode.MARKDOWN_V2)


@error_handler
async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)

    msg = group.get("goodbye")
    if not msg:
        return

    mention_enabled = group.get('goodbye_mention', True)
    m = update.message.left_chat_member

    formatted_text = _format_member_message(msg, m, update.effective_chat.title)
    if not mention_enabled:
        formatted_text = formatted_text.replace(m.mention_markdown_v2(), escape_markdown(m.full_name, version=2))
    await context.bot.send_message(chat_id=chat_id, text=formatted_text, parse_mode=ParseMode.MARKDOWN_V2)

@error_handler
async def service_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import asyncio
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    if group.get('action_delete', True) and update.effective_message:
        # Add a small delay to avoid race conditions
        await asyncio.sleep(0.5)
        await update.effective_message.delete()

@admin_only
@group_management_command_enabled_check("filter")
@error_handler
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(USAGE_FILTER_MSG)
        return
    group = load_group(chat_id)
    trigger = context.args[0].lower()
    reply = " ".join(context.args[1:])
    group['filters'][trigger] = reply
    save_group(chat_id, group)
    await update.message.reply_text(f"✅ Filter added for '{trigger}'")

@admin_only
@group_management_command_enabled_check("stop")
@error_handler
async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(USAGE_STOP_MSG)
        return
    trigger = context.args[0].lower()
    group = load_group(chat_id)
    if trigger in group['filters']:
        del group['filters'][trigger]
        save_group(chat_id, group)
        await update.message.reply_text(f"✅ Filter '{trigger}' removed")
    else:
        await update.message.reply_text("❌ Filter not found.")

def _check_entities(update: Update, entity_type: str) -> bool:
    """Helper to check for entities in a message or its caption."""
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == entity_type:
                return True
    if update.message.caption_entities:
        for entity in update.message.caption_entities:
            if entity.type == entity_type:
                return True
    return False

@error_handler
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

    should_delete = False

    # Mapping of lock types to message attributes/conditions
    lock_checks = {
        "all": True,  # If "all" is locked, always delete
        "text": update.message.text,
        "photo": update.message.photo,
        "video": update.message.video,
        "audio": update.message.audio,
        "voice": update.message.voice,
        "document": update.message.document,
        "gif": update.message.animation,
        "sticker": update.message.sticker,
        "emoji": _check_entities(update, "custom_emoji"),
        "video_note": update.message.video_note,
        "album": update.message.media_group_id,
        "contact": update.message.contact,
        "location": update.message.location,
        "poll": update.message.poll,
        "game": update.message.game,
        "inline": update.message.via_bot,
        "forward": update.message and update.message.forward_date,
        "forwardbot": update.message.forward_from and update.message.forward_from.is_bot,
        "forwardchannel": update.message.forward_from_chat and update.message.forward_from_chat.type == "channel",
        "forwarduser": update.message.forward_from and not update.message.forward_from.is_bot,
        "url": _check_entities(update, "url"),
        "email": _check_entities(update, "email"),
        "cashtag": _check_entities(update, "cashtag"),
        "command": _check_entities(update, "bot_command"),
        "phone": _check_entities(update, "phone_number"),
        "spoiler": _check_entities(update, "spoiler"),
        "anonchannel": update.message.sender_chat and update.message.sender_chat.type == "channel" and update.message.sender_chat.is_anonymous,
        "botlink": _check_entities(update, "text_link") and "t.me/" in (update.message.text or update.message.caption or ""),
        "invitelink": _check_entities(update, "text_link") and ("t.me/joinchat/" in (update.message.text or update.message.caption or "") or "t.me/+" in (update.message.text or update.message.caption or "")),
    }

    for lock_type, condition in lock_checks.items():
        if locks.get(lock_type) and condition:
            should_delete = True
            break

    if should_delete:
        await update.message.delete()


@error_handler
async def filter_responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    group = load_group(chat_id)
    for trigger, reply in group.get("filters", {}).items():
        if trigger in text:
            await update.message.reply_text(reply)
            break



# --------------------- Moderation ---------------------

@admin_only
@group_management_command_enabled_check("mute")
@error_handler
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_MUTE_BAN_MSG)
        return

    await context.bot.restrict_chat_member(
        chat_id,
        target_user_id,
        permissions=ChatPermissions(can_send_messages=False)
    )
    await update.message.reply_text("🔇 User muted.")

@admin_only
@group_management_command_enabled_check("tmute")
@error_handler
async def tmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_MUTE_BAN_MSG)
        return

    duration_str = context.args[0] if context.args else "1h"
    duration_sec = parse_time(duration_str)
    if duration_sec == 0:
        await update.message.reply_text(INVALID_TIME_FORMAT_MSG)
        return
    
    until_date = time.time() + duration_sec
    await context.bot.restrict_chat_member(
        chat_id,
        target_user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=int(until_date)
    )
    await update.message.reply_text(f"🔇 User muted for {duration_str}.")

@admin_only
@group_management_command_enabled_check("unmute")
@error_handler
async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions=ChatPermissions(can_send_messages=True, can_send_photos=True, can_send_videos=True, can_send_audios=True, can_send_voice_notes=True, can_send_documents=True, can_send_video_notes=True, can_send_other_messages=True, can_add_web_page_previews=True)
    )
    await update.message.reply_text("🔊 User unmuted.")

@admin_only
@group_management_command_enabled_check("kick")
@error_handler
async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_KICK_MSG)
        return

    await context.bot.ban_chat_member(chat_id, target_user_id)
    await context.bot.unban_chat_member(chat_id, target_user_id)
    await update.message.reply_text("👢 User kicked.")

@admin_only
@group_management_command_enabled_check("ban")
@error_handler
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_BAN_MSG)
        return

    await context.bot.ban_chat_member(chat_id, target_user_id)
    await update.message.reply_text("🚫 User banned.")

@admin_only
@group_management_command_enabled_check("tban")
@error_handler
async def tban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(NO_ADMIN_TBAN_MSG)
        return

    duration_str = context.args[0] if context.args else "1d"
    duration_sec = parse_time(duration_str)
    if duration_sec == 0:
        await update.message.reply_text(INVALID_TIME_FORMAT_MSG)
        return
        
    until_date = time.time() + duration_sec
    await context.bot.ban_chat_member(chat_id, target_user_id, until_date=int(until_date))
    await update.message.reply_text(f"🚫 User banned for {duration_str}.")

@admin_only
@group_management_command_enabled_check("unban")
@error_handler
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(USAGE_UNBAN_MSG)
        return
    user_id = int(context.args[0])
    await context.bot.unban_chat_member(update.effective_chat.id, user_id)
    await update.message.reply_text("✅ User unbanned.")

# --------------------- Warning System ---------------------

@admin_only
@group_management_command_enabled_check("warn")
@error_handler
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user = update.message.reply_to_message.from_user

    if await is_user_admin(context, chat_id, target_user.id):
        await update.message.reply_text(NO_ADMIN_WARN_MSG)
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

@admin_only
@group_management_command_enabled_check("warns")
@error_handler
async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return
    
    chat_id = update.effective_chat.id
    target_user = update.message.reply_to_message.from_user
    group = load_group(chat_id)
    
    count = group.get('warn_counts', {}).get(str(target_user.id), 0)
    await update.message.reply_text(f"User {target_user.mention_markdown_v2()} has {count} warnings.", parse_mode="MarkdownV2")

@admin_only
@group_management_command_enabled_check("warnlimit")
@error_handler
async def set_warn_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(USAGE_WARN_LIMIT_MSG)
        return
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    group['warn_limit'] = int(context.args[0])
    save_group(chat_id, group)
    await update.message.reply_text(f"✅ Warning limit set to {context.args[0]}.")

@admin_only
@group_management_command_enabled_check("warnmode")
@error_handler
async def set_warn_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ['mute', 'kick', 'ban']:
        await update.message.reply_text(USAGE_WARN_MODE_MSG)
        return
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    group['warn_mode'] = context.args[0].lower()
    save_group(chat_id, group)
    await update.message.reply_text(f"✅ Warning mode set to {context.args[0].lower()}.")


# --------------------- Group Settings ---------------------

LOCKABLE_TYPES = [
    "album", "anonchannel", "audio", "bot", "cashtag", "command", "contact", 
    "document", "email", "emoji", "emojicustom", "emojigame", "externalreply", "forward", 
    "forwardbot", "forwardchannel", "forwarduser", "game", "gif", "inline", 
    "location", "phone", "photo", "poll", "spoiler", "sticker", "stickeranimated", 
    "stickerpremium", "text", "url", "video", "videonote", "voice"
]

def _build_locks_keyboard(locks: dict) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for i, lock_type in enumerate(LOCKABLE_TYPES):
        status_icon = "🔒" if locks.get(lock_type) else "🔓"
        button = InlineKeyboardButton(f"{status_icon} {lock_type.capitalize()}", callback_data=f"toggle_lock_{lock_type}")
        row.append(button)
        if (i + 1) % 2 == 0 or i == len(LOCKABLE_TYPES) - 1: # Two columns or last button
            keyboard.append(row)
            row = []

    keyboard.append([
        InlineKeyboardButton("Lock All", callback_data="toggle_lock_all_lock"),
        InlineKeyboardButton("Unlock All", callback_data="toggle_lock_all_unlock")
    ])
    return InlineKeyboardMarkup(keyboard)

@admin_only
@group_management_command_enabled_check("locks")
@bot_has_permissions(["can_change_info"])
@error_handler
async def locks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    locks = group.setdefault("locks", {})

    reply_markup = _build_locks_keyboard(locks)
    await update.message.reply_text("🔧 Manage group locks:", reply_markup=reply_markup)

@bot_has_permissions(["can_restrict_members", "can_delete_messages"])
@error_handler
async def locks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not query.message:
        await query.edit_message_text("This button is no longer valid or the message is inaccessible.")
        return

    chat_id = query.message.chat.id
    if not await is_user_admin(context, chat_id, query.from_user.id):
        # No need for another answer, just return
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
    permissions_data["can_send_polls"] = not locks.get("poll", False)
    permissions_data["can_send_other_messages"] = not (locks.get("emoji", False) or locks.get("sticker", False) or locks.get("gif", False))
    permissions_data["can_add_web_page_previews"] = not locks.get("previews", False)

    permissions = ChatPermissions(**permissions_data)

    # Rebuild the keyboard with updated status
    reply_markup = _build_locks_keyboard(locks)
    await query.edit_message_text("🔧 Manage group locks:", reply_markup=reply_markup)
    await query.answer(text="✅ Settings updated and applied!")

@admin_only
@group_management_command_enabled_check("pin")
@bot_has_permissions(["can_pin_messages"])
@error_handler
async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notify = 'loud' in context.args
    
    if update.message.reply_to_message:
        message_id = update.message.reply_to_message.message_id
    elif context.args:
        # This part is tricky as we can't just "pin text". We pin a message.
        # So the bot will send a message first, then pin it.
        text_to_pin = " ".join(arg for arg in context.args if arg != 'loud')
        if not text_to_pin:
            await update.message.reply_text(USAGE_PIN_MSG)
            return
        sent_message = await update.message.reply_text(text_to_pin)
        message_id = sent_message.message_id
    else:
        await update.message.reply_text(REPLY_TO_USER_MSG + " or provide text to pin.")
        return
        
    await context.bot.pin_chat_message(
        chat_id=update.effective_chat.id,
        message_id=message_id,
        disable_notification=not notify
    )

@admin_only
@group_management_command_enabled_check("action")
@error_handler
async def action_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
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

@error_handler
async def action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await is_user_admin(context, query.message.chat.id, query.from_user.id):
        await query.edit_message_text(ADMIN_PERMISSION_MSG)
        return
    
    chat_id = query.message.chat.id
    group = load_group(chat_id)
    
    new_state = query.data == "action_set_on"
    group['action_delete'] = new_state
    save_group(chat_id, group)
    
    status = "ON" if new_state else "OFF"
    await query.edit_message_text(f"✅ Service message auto-deletion is now **{status}**.", parse_mode="Markdown")

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
    return ChatAdministratorRights() # Return empty rights if not admin or error

@admin_only
@group_management_command_enabled_check("promote")
@bot_has_permissions(["can_promote_members"])
@error_handler
async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    user_id = update.message.reply_to_message.from_user.id
    chat_id = update.effective_chat.id
    custom_title = " ".join(context.args) if context.args else "Admin"

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

def _build_permissions_keyboard(target_user_id: int, current_rights_dict: dict) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for i, (perm_key, perm_name) in enumerate(PERMISSION_MAP.items()):
        status_icon = "✅" if current_rights_dict.get(perm_name) else "❌"
        button = InlineKeyboardButton(
            f"{status_icon} {perm_key.replace('_', ' ').capitalize()}", 
            callback_data=f"toggle_perm_{target_user_id}_{perm_key}"
        )
        row.append(button)
        if (i + 1) % 2 == 0 or i == len(PERMISSION_MAP) - 1: # Two columns or last button
            keyboard.append(row)
            row = []
    return InlineKeyboardMarkup(keyboard)

@admin_only
@group_management_command_enabled_check("permissions")
@bot_has_permissions(["can_promote_members"])
@error_handler
async def permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    member = await context.bot.get_chat_member(chat_id, target_user_id)
    if not await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(USER_NOT_ADMIN_PROMOTE_FIRST_MSG)
        return

    current_rights_dict = {}
    for perm_key, perm_name in PERMISSION_MAP.items():
        current_rights_dict[perm_name] = getattr(member, perm_name, False)

    reply_markup = _build_permissions_keyboard(target_user_id, current_rights_dict)
    await update.message.reply_text(
        f"🔧 Managing permissions for {member.user.first_name}:",
        reply_markup=reply_markup
    )

@bot_has_permissions(["can_promote_members"])
@error_handler
async def permissions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    chat_id = query.message.chat.id
    requesting_user_id = query.from_user.id

    if not await is_user_admin(context, chat_id, requesting_user_id):
        await query.answer(text=ADMIN_PERMISSION_MSG, show_alert=True)
        return

    _, _, target_user_id_str, perm_key = query.data.split('_', 3)
    target_user_id = int(target_user_id_str)
    permission_name = PERMISSION_MAP[perm_key]

    member = await context.bot.get_chat_member(chat_id, target_user_id)
    if member.status not in ('administrator', 'creator'):
        await query.edit_message_text(USER_NO_LONGER_ADMIN_MSG)
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

    # Only grant rights that the bot itself has
    for right, value in updated_rights_dict.items():
        if value and not getattr(bot_rights, right, False):
            updated_rights_dict[right] = False # Bot cannot grant what it doesn't have
    
    new_rights = ChatAdministratorRights(**updated_rights_dict)

    await context.bot.promote_chat_member(chat_id, target_user_id, **new_rights.to_dict())
    
    # Rebuild the keyboard with updated status
    reply_markup = _build_permissions_keyboard(target_user_id, new_rights.to_dict())
    await query.edit_message_text(
        f"🔧 Managing permissions for {member.user.first_name}:",
        reply_markup=reply_markup
    )
    await query.answer(f"✅ {perm_key.capitalize()} permission updated.")

@admin_only
@group_management_command_enabled_check("demote")
@bot_has_permissions(["can_promote_members"])
@error_handler
async def demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return

    chat_id = update.effective_chat.id
    target_user_id = update.message.reply_to_message.from_user.id

    if not await is_user_admin(context, chat_id, target_user_id):
        await update.message.reply_text(USER_NOT_ADMIN_PROMOTE_FIRST_MSG)
        return

    # Demote by setting all admin rights to False
    demote_rights = {attr: False for attr in MINIMAL_ADMIN_RIGHTS.to_dict().keys()}
    await context.bot.promote_chat_member(
        chat_id=chat_id,
        user_id=target_user_id,
        **demote_rights
    )
    await update.message.reply_text("✅ User demoted.")


# --------------------- Utility ---------------------

@error_handler
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
@group_management_command_enabled_check("tagadmin")
@error_handler
async def tagadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    admins = await context.bot.get_chat_administrators(chat_id)

    mention_text = " ".join(f"@{admin.user.username}" for admin in admins if admin.user.username)
    reason = escape_markdown(" ".join(context.args), version=2)

    if not mention_text:
        await update.message.reply_text(NO_USERNAME_ADMINS_MSG)
        return

    message = f"📣 *Calling all admins\!*\n{reason}\n\n{mention_text}"
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)


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

    # Group Management Commands
    app.add_handler(CommandHandler("group_manage", group_manage_command))
    app.add_handler(CallbackQueryHandler(group_manage_callback, pattern="^group_manage_"))

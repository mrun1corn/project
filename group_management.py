import time
from asyncio import sleep
from telegram import Update, ChatPermissions, ChatAdministratorRights, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.helpers import escape_markdown
from telegram.constants import ParseMode
from telegram.error import BadRequest
from functools import wraps
from command_registry import get_default_group_commands

# --- Constants ---
ADMIN_ONLY_MSG = "🔒 You must be an admin to use this command."
ADMIN_PERMISSION_MSG = "🔒 You must be an admin to change this setting."
REPLY_TO_USER_MSG = "↩️ Reply to a user's message to use this command."
NO_ADMIN_MUTE_BAN_MSG = "⚠️ You cannot mute or ban another admin."
NO_ADMIN_KICK_MSG = "⚠️ You cannot kick another admin."
NO_ADMIN_BAN_MSG = "⚠️ You cannot ban another admin."
NO_ADMIN_TBAN_MSG = "⚠️ You cannot temporarily ban another admin."
NO_ADMIN_WARN_MSG = "⚠️ You cannot warn another admin."
INVALID_TIME_FORMAT_MSG = "⏱️ Invalid time format. Use m, h, or d. Example: /tmute 30m"
BOT_NO_RESTRICT_PERMISSION_MSG = "⚠️ I need the Restrict Members permission to do that."
BOT_NO_DELETE_PERMISSION_MSG = "⚠️ I need the Delete Messages permission to do that."
BOT_NO_PROMOTE_PERMISSION_MSG = "⚠️ I need the Promote Members permission to do that."
BOT_NO_CHANGE_INFO_PERMISSION_MSG = "⚠️ I need the Change Chat Info permission to do that."
BOT_NO_INVITE_USERS_PERMISSION_MSG = "⚠️ I need the Invite Users permission to do that."
BOT_NO_PIN_MESSAGES_PERMISSION_MSG = "⚠️ I need the Pin Messages permission to do that."
BOT_NO_MANAGE_TOPICS_PERMISSION_MSG = "⚠️ I need the Manage Topics permission to do that."
BOT_NO_DELETE_MESSAGES_PERMISSION_MSG = "⚠️ I need the Delete Messages permission to do that."
USAGE_FILTER_MSG = "🧩 Usage: /filter <keyword> <reply>"
USAGE_STOP_MSG = "🧩 Usage: /stop <keyword>"
USAGE_UNBAN_MSG = "🧾 Usage: /unban <user_id>"
USAGE_WARN_LIMIT_MSG = "⚠️ Usage: /warnlimit <number>"
USAGE_WARN_MODE_MSG = "⚠️ Usage: /warnmode <mute|kick|ban>"
USAGE_PIN_MSG = "📌 Usage: /pin [loud] <text> or reply to a message."
USAGE_PURGE_MSG = "🧹 Usage: /purge <number> or reply to a message."
NO_USERNAME_ADMINS_MSG = "ℹ️ No admins with usernames are available to tag."
USER_NOT_ADMIN_PROMOTE_FIRST_MSG = "ℹ️ That user is not an admin. Promote them first."
USER_NO_LONGER_ADMIN_MSG = "ℹ️ That user is no longer an admin."

# --- Decorators ---
def error_handler(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except BadRequest as e:
            error_text = str(e)
            print(f"Telegram error in {func.__name__}: {error_text}")
            if "chat_admin_required" in error_text.lower():
                friendly = "⚠️ I need to be an admin with the required permissions to do that. Please promote me and try again."
            else:
                friendly = f"⚠️ Telegram error: {error_text}"

            if update.message:
                await update.message.reply_text(friendly)
            elif update.callback_query:
                await update.callback_query.answer(friendly, show_alert=True)
        except Exception as e:
            print(f"Error in {func.__name__}: {e}")
            if update.message:
                await update.message.reply_text(f"⚠️ An unexpected error occurred: {e}")
            elif update.callback_query:
                await update.callback_query.answer(f"⚠️ An unexpected error occurred: {e}", show_alert=True)
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
                msg = f"⚠️ I need these permissions to do that: {', '.join(missing_permissions)}."
                if update.message:
                    await update.message.reply_text(msg)
                elif update.callback_query:
                    await update.callback_query.answer(msg, show_alert=True)
                return
            return await func(update, context, *args, **kwargs)
        return wrapped
    return decorator

from settings import settings
from database import get_collection
from toggle_ui import build_toggle_keyboard

GROUPS_COLLECTION = get_collection("group_data")
GROUP_COMMANDS_COLLECTION = get_collection("group_management_command_states")
GROUP_COMMANDS = get_default_group_commands()


async def load_group_command_states(chat_id: int) -> dict:
    doc = await GROUP_COMMANDS_COLLECTION.find_one({"_id": chat_id})
    if not doc:
        return GROUP_COMMANDS.copy()
    stored = doc.get("commands", {})
    states = GROUP_COMMANDS.copy()
    states.update({name: bool(value) for name, value in stored.items() if name in GROUP_COMMANDS})
    return states


async def save_group_command_states(chat_id: int, states: dict) -> None:
    await GROUP_COMMANDS_COLLECTION.update_one(
        {"_id": chat_id},
        {"$set": {"commands": states}},
        upsert=True,
    )


def group_management_command_enabled_check(command_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            states = await load_group_command_states(update.effective_chat.id)
            if not states.get(command_name, True):
                return
            return await func(update, context, *args, **kwargs)

        return wrapped

    return decorator


async def _build_group_manage_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    states = await load_group_command_states(chat_id)
    return build_toggle_keyboard(
        (
            (command_name.capitalize(), enabled, f"group_manage_toggle_{command_name}")
            for command_name, enabled in sorted(states.items())
        ),
        extra_rows=[
            [
                InlineKeyboardButton("Enable All", callback_data="group_manage_all_enable"),
                InlineKeyboardButton("Disable All", callback_data="group_manage_all_disable"),
            ]
        ],
    )


async def group_manage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != settings.admin_chat_id:
        await update.message.reply_text("🔒 You are not authorized to use this command.")
        return

    reply_markup = await _build_group_manage_keyboard(update.effective_chat.id)
    await update.message.reply_text("⚙️ Manage group commands from the panel below.", reply_markup=reply_markup)


async def group_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.from_user.id != settings.admin_chat_id:
        await query.answer("🔒 You are not authorized to change these settings.", show_alert=True)
        return

    chat_id = query.message.chat.id
    states = await load_group_command_states(chat_id)
    data = query.data

    if data == "group_manage_all_enable":
        for command_name in states:
            states[command_name] = True
        await save_group_command_states(chat_id, states)
        await query.edit_message_text("✅ All group management commands are now enabled.", reply_markup=await _build_group_manage_keyboard(chat_id))
        return

    if data == "group_manage_all_disable":
        for command_name in states:
            states[command_name] = False
        await save_group_command_states(chat_id, states)
        await query.edit_message_text("🛑 All group management commands are now disabled.", reply_markup=await _build_group_manage_keyboard(chat_id))
        return

    if data.startswith("group_manage_toggle_"):
        command_name = data.removeprefix("group_manage_toggle_")
        if command_name in states:
            states[command_name] = not states[command_name]
            await save_group_command_states(chat_id, states)
            status = "enabled" if states[command_name] else "disabled"
            await query.edit_message_text(
                f"Command `{command_name}` is now {status}.",
                reply_markup=await _build_group_manage_keyboard(chat_id),
                parse_mode="Markdown",
            )
            return

    await query.edit_message_text("⚠️ Invalid command selected.")

# Canonical lock keys used across storage, UI, and enforcement.
LOCKABLE_TYPES = [
    "album",
    "anonchannel",
    "audio",
    "bot",
    "botlink",
    "cashtag",
    "command",
    "contact",
    "document",
    "email",
    "emoji",
    "forward",
    "forwardbot",
    "forwardchannel",
    "forwarduser",
    "game",
    "gif",
    "inline",
    "invitelink",
    "location",
    "phone",
    "photo",
    "poll",
    "spoiler",
    "sticker",
    "stickeranimated",
    "stickerpremium",
    "text",
    "url",
    "video",
    "video_note",
    "voice",
]

# Human readable labels for lock buttons.
LOCK_LABELS = {
    "anonchannel": "Anon Channel",
    "botlink": "Bot Links",
    "invitelink": "Invite Links",
    "stickeranimated": "Animated Sticker",
    "stickerpremium": "Premium Sticker",
    "video_note": "Video Note",
}

# Format lock names for button labels.
def _lock_label(lock_type: str) -> str:
    return LOCK_LABELS.get(lock_type, lock_type.replace('_', ' ').title())

# Older persisted keys mapped to the new canonical form.
LOCK_KEY_ALIASES = {
    "videonote": "video_note",
    "videonotes": "video_note",
    "videoNote": "video_note",
    "emojicustom": "emoji",
    "emojigame": "game",
    "externalreply": "forward",
    "stickeranimated": "stickeranimated",
    "sticker_animated": "stickeranimated",
    "stickerpremium": "stickerpremium",
    "sticker_premium": "stickerpremium",
    "botlinks": "botlink",
    "invitelinks": "invitelink",
}

_group_cache: dict[int, dict] = {}

def _normalize_locks(raw_locks: dict) -> dict:
    """Normalize lock keys coming from disk to the canonical list."""
    if not isinstance(raw_locks, dict):
        return {}

    normalized = {key: False for key in LOCKABLE_TYPES}
    for key, value in raw_locks.items():
        canonical = LOCK_KEY_ALIASES.get(key, key)
        if canonical in LOCKABLE_TYPES:
            normalized[canonical] = bool(value)
    return normalized

DEFAULT_GROUP_DATA = {
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


async def load_group(chat_id: int) -> dict:
    if chat_id in _group_cache:
        return _group_cache[chat_id]

    doc = await GROUPS_COLLECTION.find_one({"_id": chat_id})
    group_data = DEFAULT_GROUP_DATA.copy()
    if doc:
        doc_data = {k: v for k, v in doc.items() if k != "_id"}
        group_data.update(doc_data)
    group_data['locks'] = _normalize_locks(group_data.get('locks', {}))

    _group_cache[chat_id] = group_data
    return group_data


async def save_group(chat_id: int, data: dict) -> None:
    _group_cache[chat_id] = data
    to_store = data.copy()
    await GROUPS_COLLECTION.update_one({"_id": chat_id}, {"$set": to_store}, upsert=True)

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
    group = await load_group(chat_id)

    if not context.args:
        await update.message.reply_text(f"Welcome message:\n{group['welcome'] or 'Disabled'}")
        return

    arg = " ".join(context.args)
    if arg.lower() in ['off', 'no']:
        group['welcome'] = None
        await update.message.reply_text("Welcome message disabled.")
    else:
        group['welcome'] = arg
        await update.message.reply_text(f"Welcome message set to:\n{arg}")

    await save_group(chat_id, group)


@admin_only
@group_management_command_enabled_check("goodbye")
@error_handler
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)

    if not context.args:
        await update.message.reply_text(f"Goodbye message:\n{group['goodbye'] or 'Disabled'}")
        return

    arg = " ".join(context.args)
    if arg.lower() in ['off', 'no']:
        group['goodbye'] = None
        await update.message.reply_text("Goodbye message disabled.")
    else:
        group['goodbye'] = arg
        await update.message.reply_text(f"Goodbye message set to:\n{arg}")

    await save_group(chat_id, group)



@error_handler
async def mention_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await is_user_admin(context, query.message.chat.id, query.from_user.id):
        await query.edit_message_text(ADMIN_PERMISSION_MSG)
        return
    
    chat_id = query.message.chat.id
    group = await load_group(chat_id)
    
    _, type, choice = query.data.split('_')
    
    mention_enabled = choice == 'yes'
    group[f'{type}_mention'] = mention_enabled
    await save_group(chat_id, group)
    
    await query.edit_message_text(f"User mentions for {type} message have been {'enabled' if mention_enabled else 'disabled'}.")

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
    group = await load_group(chat_id)

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
    group = await load_group(chat_id)

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
    group = await load_group(chat_id)
    
    # Only proceed if auto-deletion is enabled for the group
    if not group.get('action_delete', True) or not update.effective_message:
        return

    # Check if the bot has permission to delete messages
    bot_rights = await get_bot_admin_rights(context, chat_id)
    if not bot_rights.can_delete_messages:
        # Silently return if the bot can't delete messages to avoid spamming logs or chats
        return

    try:
        # Add a small delay to avoid race conditions
        await asyncio.sleep(0.5)
        await update.effective_message.delete()
    except Exception as e:
        # Catch potential errors during deletion (e.g., message too old) and log them
        print(f"Could not delete service message in chat {chat_id}: {e}")

@admin_only
@group_management_command_enabled_check("filter")
@error_handler
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(USAGE_FILTER_MSG)
        return
    group = await load_group(chat_id)
    trigger = context.args[0].lower()
    reply = " ".join(context.args[1:])
    group['filters'][trigger] = reply
    await save_group(chat_id, group)
    await update.message.reply_text(f"Filter added for '{trigger}'")

@admin_only
@group_management_command_enabled_check("stop")
@error_handler
async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(USAGE_STOP_MSG)
        return
    trigger = context.args[0].lower()
    group = await load_group(chat_id)
    if trigger in group['filters']:
        del group['filters'][trigger]
        await save_group(chat_id, group)
        await update.message.reply_text(f"Filter '{trigger}' removed")
    else:
        await update.message.reply_text("Filter not found.")

def _check_entities(update: Update, entity_types) -> bool:
    """Helper to check for entities in a message or its caption."""
    if not update.message:
        return False

    if isinstance(entity_types, str):
        entity_types = (entity_types,)

    # Safely get entities and caption_entities, defaulting to empty lists if not present
    entities = getattr(update.message, 'entities', []) or []
    caption_entities = getattr(update.message, 'caption_entities', []) or []

    for entity in entities:
        if entity.type in entity_types:
            return True
    for entity in caption_entities:
        if entity.type in entity_types:
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

    group = await load_group(chat_id)
    locks = group.get("locks", {})

    should_delete = False

    try:
        message = update.message
        text_or_caption = getattr(message, 'text', None) or getattr(message, 'caption', None) or ""

        # Explicitly check for forward and sender_chat related attributes
        is_forwarded_from_bot = False
        is_forwarded_from_channel = False
        is_forwarded_from_user = False
        is_anonymous_channel_sender = False

        forward_from = getattr(message, 'forward_from', None)
        if forward_from:
            if getattr(forward_from, 'is_bot', False):
                is_forwarded_from_bot = True
            else:
                is_forwarded_from_user = True

        forward_from_chat = getattr(message, 'forward_from_chat', None)
        if forward_from_chat and getattr(forward_from_chat, 'type', None) == "channel":
            is_forwarded_from_channel = True

        sender_chat = getattr(message, 'sender_chat', None)
        if sender_chat and getattr(sender_chat, 'type', None) == "channel" and getattr(sender_chat, 'is_anonymous', False):
            is_anonymous_channel_sender = True

        new_members = getattr(message, 'new_chat_members', None) or []
        bot_members = [member for member in new_members if getattr(member, 'is_bot', False)]
        bots_joining = bool(bot_members)

        lock_checks = {
            "album": bool(getattr(message, 'media_group_id', None)),
            "anonchannel": is_anonymous_channel_sender,
            "audio": bool(getattr(message, 'audio', None)),
            "bot": bots_joining,
            "botlink": _check_entities(update, ("url", "text_link")) and (
                "t.me/" in text_or_caption
            ),
            "cashtag": _check_entities(update, "cashtag"),
            "command": _check_entities(update, "bot_command"),
            "contact": bool(getattr(message, 'contact', None)),
            "document": bool(getattr(message, 'document', None)),
            "email": _check_entities(update, "email"),
            "emoji": _check_entities(update, ("custom_emoji",)),
            "forward": bool(getattr(message, 'forward_date', None)),
            "forwardbot": is_forwarded_from_bot,
            "forwardchannel": is_forwarded_from_channel,
            "forwarduser": is_forwarded_from_user,
            "game": bool(getattr(message, 'game', None)),
            "gif": bool(getattr(message, 'animation', None)),
            "inline": bool(getattr(message, 'via_bot', None)),
            "invitelink": _check_entities(update, ("url", "text_link")) and (
                "t.me/joinchat/" in text_or_caption or "t.me/+" in text_or_caption
            ),
            "location": bool(getattr(message, 'location', None)),
            "phone": _check_entities(update, "phone_number"),
            "photo": bool(getattr(message, 'photo', None)),
            "poll": bool(getattr(message, 'poll', None)),
            "spoiler": _check_entities(update, "spoiler"),
            "sticker": bool(getattr(message, 'sticker', None) and not (
                getattr(message.sticker, "is_animated", False)
                or getattr(message.sticker, "is_video", False)
                or getattr(message.sticker, "is_premium", False)
            )),
            "stickeranimated": bool(getattr(message, 'sticker', None) and (
                getattr(message.sticker, "is_animated", False)
                or getattr(message.sticker, "is_video", False)
            )),
            "stickerpremium": bool(getattr(message, 'sticker', None) and getattr(message.sticker, "is_premium", False)),
            "text": bool(text_or_caption.strip()),
            "url": _check_entities(update, ("url", "text_link")),
            "video": bool(getattr(message, 'video', None)),
            "video_note": bool(getattr(message, 'video_note', None)),
            "voice": bool(getattr(message, 'voice', None)),
        }

        triggered_locks = [lock_type for lock_type, condition in lock_checks.items() if locks.get(lock_type) and condition]

        if "bot" in triggered_locks and bot_members:
            bot_rights = await get_bot_admin_rights(context, chat_id)
            if bot_rights.can_restrict_members:
                for member in bot_members:
                    try:
                        await context.bot.ban_chat_member(chat_id, member.id)
                        await context.bot.unban_chat_member(chat_id, member.id)
                    except Exception as e:
                        print(f"Error removing bot {member.id} from chat {chat_id}: {e}")
            else:
                print(f"Missing restrict_members permission to enforce bot lock in chat {chat_id}")

        should_delete = bool(triggered_locks)
    except AttributeError as e:
        print(f"AttributeError in enforce_locks during lock_checks creation: {e}")
        triggered_locks = []
        should_delete = False
    except Exception as e:
        print(f"Unexpected error in enforce_locks during lock_checks creation: {e}")
        triggered_locks = []
        should_delete = False

    if should_delete:
        try:
            await update.message.delete()
        except Exception as e:
            print(f"Failed to delete locked message in chat {chat_id}: {e}")


@error_handler
async def filter_responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    group = await load_group(chat_id)
    for trigger, reply in group.get("filters", {}).items():
        if trigger in text:
            await update.message.reply_text(reply)
            break



# --------------------- Moderation ---------------------

@admin_only
@group_management_command_enabled_check("mute")
@bot_has_permissions(["can_restrict_members"])
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
    await update.message.reply_text("User muted.")

@admin_only
@group_management_command_enabled_check("tmute")
@bot_has_permissions(["can_restrict_members"])
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
    await update.message.reply_text(f"User muted for {duration_str}.")

@admin_only
@group_management_command_enabled_check("unmute")
@bot_has_permissions(["can_restrict_members"])
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
    await update.message.reply_text("User unmuted.")

@admin_only
@group_management_command_enabled_check("kick")
@bot_has_permissions(["can_restrict_members"])
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
    await update.message.reply_text("User kicked.")

@admin_only
@group_management_command_enabled_check("ban")
@bot_has_permissions(["can_restrict_members"])
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
    await update.message.reply_text("User banned.")

@admin_only
@group_management_command_enabled_check("tban")
@bot_has_permissions(["can_restrict_members"])
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
    await update.message.reply_text(f"User banned for {duration_str}.")

@admin_only
@group_management_command_enabled_check("unban")
@bot_has_permissions(["can_restrict_members"])
@error_handler
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(USAGE_UNBAN_MSG)
        return
    user_id = int(context.args[0])
    await context.bot.unban_chat_member(update.effective_chat.id, user_id)
    await update.message.reply_text("User unbanned.")

@admin_only
@group_management_command_enabled_check("purge")
@bot_has_permissions(["can_delete_messages"])
@error_handler
async def purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(USAGE_PURGE_MSG)
        return

    chat_id = update.effective_chat.id
    message_ids_to_delete = []

    try:
        if update.message.reply_to_message:
            start_message_id = update.message.reply_to_message.message_id
            num_messages = int(context.args[0]) if context.args else 1
            
            # Fetch messages from start_message_id backwards
            # Telegram Bot API doesn't have a direct way to fetch messages by range or count backwards easily.
            # The most reliable way is to iterate and delete.
            # For simplicity and to avoid hitting API limits with too many getUpdates,
            # we'll assume a simple deletion from the current message backwards.
            # A more robust solution would involve storing message IDs or using a different API.
            
            # For now, we'll delete from the replied message up to 'num_messages' messages.
            # This is a simplification. A real implementation might need to fetch message history.
            for i in range(num_messages):
                message_ids_to_delete.append(start_message_id - i)
        else:
            num_messages = int(context.args[0])
            # Delete the last 'num_messages' messages including the command message itself
            for i in range(num_messages + 1): # +1 to include the command message
                message_ids_to_delete.append(update.message.message_id - i)

        # Ensure unique message IDs and sort them for bulk deletion if API supports it
        message_ids_to_delete = sorted(list(set(message_ids_to_delete)))
        
        # Telegram's deleteMessages only works for messages less than 48 hours old
        # and up to 100 messages at once.
        # We'll delete them one by one for simplicity and to handle older messages if needed,
        # though bulk deletion is more efficient for recent messages.
        
        deleted_count = 0
        for msg_id in message_ids_to_delete:
            try:
                await context.bot.delete_message(chat_id, msg_id)
                deleted_count += 1
            except Exception as e:
                # Log error but continue with other messages
                print(f"Error deleting message {msg_id} in chat {chat_id}: {e}")
        
        await context.bot.send_message(chat_id, f"Purged {deleted_count} messages.")

    except ValueError:
        await update.message.reply_text(USAGE_PURGE_MSG)
    except Exception as e:
        await update.message.reply_text(f"An error occurred during purge: {e}")

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

    group = await load_group(chat_id)
    
    warn_counts = group.setdefault('warn_counts', {})
    user_id_str = str(target_user.id)
    warn_counts[user_id_str] = warn_counts.get(user_id_str, 0) + 1
    
    limit = group.get('warn_limit', 3)
    reason = " ".join(context.args).strip()
    default_reason = escape_markdown("No reason specified", version=2)
    reason_text = escape_markdown(reason, version=2) if reason else default_reason

    warn_message = (
        f"Warned {target_user.mention_markdown_v2()} "
        f"\\({warn_counts[user_id_str]}/{limit}\\).\n"
        f"Reason: {reason_text}"
    )

    await update.message.reply_text(warn_message, parse_mode="MarkdownV2")

    if warn_counts[user_id_str] >= limit:
        mode = group.get('warn_mode', 'mute')
        await update.message.reply_text(f"User reached warning limit. Action: {mode.capitalize()}.")
        if mode == 'kick':
            await kick(update, context)
        elif mode == 'ban':
            await ban(update, context)
        else: # mute
            await mute(update, context)
        warn_counts[user_id_str] = 0 # Reset warnings

    await save_group(chat_id, group)

@admin_only
@group_management_command_enabled_check("warns")
@error_handler
async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(REPLY_TO_USER_MSG)
        return
    
    chat_id = update.effective_chat.id
    target_user = update.message.reply_to_message.from_user
    group = await load_group(chat_id)
    
    count = group.get('warn_counts', {}).get(str(target_user.id), 0)
    await update.message.reply_text(
        f"User {target_user.mention_markdown_v2()} has {count} warnings\\.",
        parse_mode="MarkdownV2"
    )

@admin_only
@group_management_command_enabled_check("warnlimit")
@error_handler
async def set_warn_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(USAGE_WARN_LIMIT_MSG)
        return
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)
    group['warn_limit'] = int(context.args[0])
    await save_group(chat_id, group)
    await update.message.reply_text(f"Warning limit set to {context.args[0]}.")

@admin_only
@group_management_command_enabled_check("warnmode")
@error_handler
async def set_warn_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ['mute', 'kick', 'ban']:
        await update.message.reply_text(USAGE_WARN_MODE_MSG)
        return
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)
    group['warn_mode'] = context.args[0].lower()
    await save_group(chat_id, group)
    await update.message.reply_text(f"Warning mode set to {context.args[0].lower()}.")


# --------------------- Group Settings ---------------------

def _build_locks_keyboard(locks: dict) -> InlineKeyboardMarkup:
    return build_toggle_keyboard(
        (
            (_lock_label(lock_type), locks.get(lock_type, False), f"toggle_lock_{lock_type}")
            for lock_type in LOCKABLE_TYPES
        ),
        extra_rows=[
            [
                InlineKeyboardButton("Lock All", callback_data="toggle_lock_all_lock"),
                InlineKeyboardButton("Unlock All", callback_data="toggle_lock_all_unlock"),
            ]
        ],
    )

@admin_only
@group_management_command_enabled_check("locks")
@bot_has_permissions(["can_change_info", "can_restrict_members"])
@error_handler
async def locks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = await load_group(chat_id)
    locks = group.setdefault("locks", {})
    for key in LOCKABLE_TYPES:
        locks.setdefault(key, False)

    reply_markup = _build_locks_keyboard(locks)
    await update.message.reply_text("Manage group locks:", reply_markup=reply_markup)

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

    group = await load_group(chat_id)
    locks = group.setdefault("locks", {})
    for key in LOCKABLE_TYPES:
        locks.setdefault(key, False)
    original_locks = locks.copy()

    _, _, *data = query.data.split('_')
    if not data:
        await query.answer("Invalid option.", show_alert=True)
        return

    raw_lock = data[0]

    if raw_lock == "all":
        if len(data) < 2:
            await query.answer("Invalid option.", show_alert=True)
            return
        action = data[1]
        for l_type in LOCKABLE_TYPES:
            locks[l_type] = action == "lock"
    else:
        lock_type = LOCK_KEY_ALIASES.get(raw_lock, raw_lock)
        if lock_type not in LOCKABLE_TYPES:
            await query.edit_message_text("Invalid lock selected.")
            return
        locks[lock_type] = not locks.get(lock_type, False)

    if original_locks == locks:
        await query.answer(text="No changes were made.")
        return

    await save_group(chat_id, group)

    # Apply permissions to the chat
    permissions_data = {
        "can_send_messages": not locks.get("text", False),
        "can_send_photos": not locks.get("photo", False),
        "can_send_videos": not locks.get("video", False),
        "can_send_audios": not locks.get("audio", False),
        "can_send_voice_notes": not locks.get("voice", False),
        "can_send_documents": not locks.get("document", False),
        "can_send_video_notes": not locks.get("video_note", False),
        "can_send_polls": not locks.get("poll", False),
        "can_send_other_messages": not (
            locks.get("gif", False)
            or locks.get("sticker", False)
            or locks.get("stickeranimated", False)
            or locks.get("stickerpremium", False)
            or locks.get("emoji", False)
            or locks.get("game", False)
        ),
        "can_add_web_page_previews": not (
            locks.get("url", False)
            or locks.get("botlink", False)
            or locks.get("invitelink", False)
        ),
        "can_change_info": True,
        "can_invite_users": True,
        "can_pin_messages": True,
        "can_manage_topics": True,
    }

    permissions = ChatPermissions(**permissions_data)

    # Rebuild the keyboard with updated status
    reply_markup = _build_locks_keyboard(locks)
    await query.edit_message_text("Manage group locks:", reply_markup=reply_markup)

    try:
        await context.bot.set_chat_permissions(chat_id, permissions)
    except Exception as e:
        print(f"Failed to apply chat permissions for chat {chat_id}: {e}")
        await query.answer("Locks updated, but I couldn't apply chat permissions.", show_alert=True)
    else:
        await query.answer(text="Settings updated and applied.")

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
    group = await load_group(chat_id)
    current_state = group.get('action_delete', True)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Auto-Delete ON", callback_data="action_set_on")],
        [InlineKeyboardButton("Auto-Delete OFF", callback_data="action_set_off")]
    ])

    await update.message.reply_text(
        f"Service Message Control\n\nCurrently, service messages are automatically deleted: **{'ON' if current_state else 'OFF'}**.\n\nChoose a new setting:",
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
    group = await load_group(chat_id)
    
    new_state = query.data == "action_set_on"
    group['action_delete'] = new_state
    await save_group(chat_id, group)
    
    status = "ON" if new_state else "OFF"
    await query.edit_message_text(f"Service message auto-deletion is now **{status}**.", parse_mode="Markdown")

# --------------------- Admin Roles ---------------------

MINIMAL_ADMIN_RIGHTS = ChatAdministratorRights(
    can_manage_chat=True, can_delete_messages=False, can_manage_video_chats=False,
    can_restrict_members=False, can_promote_members=False, can_change_info=False,
    can_invite_users=False, can_pin_messages=False, is_anonymous=False,
    can_manage_topics=False, can_post_stories=False, can_edit_stories=False,
    can_delete_stories=False
)

def _chat_admin_rights_to_dict(rights: ChatAdministratorRights) -> dict:
    """Converts a ChatAdministratorRights object to a dictionary."""
    return {
        "can_manage_chat": rights.can_manage_chat,
        "can_delete_messages": rights.can_delete_messages,
        "can_manage_video_chats": rights.can_manage_video_chats,
        "can_restrict_members": rights.can_restrict_members,
        "can_promote_members": rights.can_promote_members,
        "can_change_info": rights.can_change_info,
        "can_invite_users": rights.can_invite_users,
        "can_pin_messages": rights.can_pin_messages,
        "is_anonymous": rights.is_anonymous,
        "can_manage_topics": rights.can_manage_topics,
        "can_post_stories": rights.can_post_stories,
        "can_edit_stories": rights.can_edit_stories,
        "can_delete_stories": rights.can_delete_stories,
    }

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
    
    # Return a ChatAdministratorRights object with all permissions set to False
    return ChatAdministratorRights(
        can_manage_chat=False, can_delete_messages=False, can_manage_video_chats=False,
        can_restrict_members=False, can_promote_members=False, can_change_info=False,
        can_invite_users=False, can_pin_messages=False, is_anonymous=False,
        can_manage_topics=False, can_post_stories=False, can_edit_stories=False,
        can_delete_stories=False
    )

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
    promotable_rights = _chat_admin_rights_to_dict(MINIMAL_ADMIN_RIGHTS)

    # Only grant rights that the bot itself has
    for right, value in promotable_rights.items():
        if value and not getattr(bot_rights, right, False):
            promotable_rights[right] = False # Bot cannot grant what it doesn't have

    await context.bot.promote_chat_member(
        chat_id=chat_id, user_id=user_id, **promotable_rights
    )
    try:
        await context.bot.set_chat_administrator_custom_title(chat_id, user_id, custom_title)
    except BadRequest as e:
        if "not enough rights" in str(e).lower():
            await update.message.reply_text("Promoted, but I cannot set custom titles. Grant me the ability to manage chat info.")
        else:
            raise
    await update.message.reply_text(f"Promoted with title: {custom_title}")

def _build_permissions_keyboard(target_user_id: int, current_rights_dict: dict) -> InlineKeyboardMarkup:
    return build_toggle_keyboard(
        (
            (
                perm_key.replace("_", " ").capitalize(),
                bool(current_rights_dict.get(perm_name, False)),
                f"toggle_perm_{target_user_id}_{perm_key}",
            )
            for perm_key, perm_name in PERMISSION_MAP.items()
        ),
    )

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
        f"Managing permissions for {member.user.first_name}:",
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
        await query.answer(f"I don't have permission to change '{perm_key}'.", show_alert=True)
        return

    # Start with a base of all permissions (e.g., MINIMAL_ADMIN_RIGHTS)
    # Then overlay the current permissions from the member object
    # Finally, apply the toggled permission
    updated_rights_dict = _chat_admin_rights_to_dict(MINIMAL_ADMIN_RIGHTS)
    for perm_key_map, perm_name_map in PERMISSION_MAP.items():
        updated_rights_dict[perm_name_map] = getattr(member, perm_name_map, False)

    # Toggle the specific permission
    updated_rights_dict[permission_name] = not updated_rights_dict.get(permission_name, False)

    # Only grant rights that the bot itself has
    for right, value in updated_rights_dict.items():
        if value and not getattr(bot_rights, right, False):
            updated_rights_dict[right] = False # Bot cannot grant what it doesn't have
    
    new_rights = ChatAdministratorRights(**updated_rights_dict)

    await context.bot.promote_chat_member(chat_id, target_user_id, **_chat_admin_rights_to_dict(new_rights))
    
    # Rebuild the keyboard with updated status
    reply_markup = _build_permissions_keyboard(target_user_id, _chat_admin_rights_to_dict(new_rights))
    await query.edit_message_text(
        f"Managing permissions for {member.user.first_name}:",
        reply_markup=reply_markup
    )
    await query.answer(f"{perm_key.capitalize()} permission updated.")

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
    demote_rights = {attr: False for attr in _chat_admin_rights_to_dict(MINIMAL_ADMIN_RIGHTS).keys()}
    await context.bot.promote_chat_member(
        chat_id=chat_id,
        user_id=target_user_id,
        **demote_rights
    )
    await update.message.reply_text("User demoted.")


# --------------------- Utility ---------------------

@error_handler
async def update_member_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Keeps a list of active members."""
    if not update.message or not update.message.from_user:
        return
    chat_id = update.effective_chat.id
    user = update.message.from_user
    group = await load_group(chat_id)
    members = group.setdefault('members', {})
    members[str(user.id)] = user.username or user.first_name
    # Removed save_group here to prevent excessive disk I/O.
    # Member list persistence will need a separate, less frequent mechanism if desired.

@group_management_command_enabled_check("tagadmin")
@error_handler
async def tagadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    def escape_html(text: str) -> str:
        """A simple HTML escaper to replace the one not in the library."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    chat_id = update.effective_chat.id
    admins = await context.bot.get_chat_administrators(chat_id)

    # Create proper HTML mentions: <a href="tg://user?id=USER_ID">@username</a>
    admin_mentions = [
        f'<a href="tg://user?id={admin.user.id}">@{escape_html(admin.user.username)}</a>'
        for admin in admins if admin.user.username
    ]

    if not admin_mentions:
        await update.message.reply_text(NO_USERNAME_ADMINS_MSG)
        return

    reason = escape_html(" ".join(context.args))
    header = f"Calling all admins!\n{reason}\n\n"
    
    MESSAGE_LIMIT = 4000

    message_chunks = []
    current_chunk = header

    for mention in admin_mentions:
        if len(current_chunk) + len(mention) + 1 > MESSAGE_LIMIT:
            message_chunks.append(current_chunk)
            current_chunk = ""
        
        if not current_chunk:
            current_chunk = mention
        else:
            current_chunk += " " + mention

    if current_chunk:
        message_chunks.append(current_chunk)

    for i, chunk in enumerate(message_chunks):
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
        except Exception as e:
            print(f"Error sending admin tag chunk {i+1}/{len(message_chunks)}: {e}")
            await update.message.reply_text(f"Couldn't send a part of the admin list (chunk {i+1}).")




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
    app.add_handler(CommandHandler("purge", purge))

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



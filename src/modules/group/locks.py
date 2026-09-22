from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.core.ui import build_toggle_keyboard
from .constants import (
    ADMIN_PERMISSION_MSG,
    LOCK_KEY_ALIASES,
    LOCKABLE_TYPES,
)
from .permissions import (
    admin_only,
    bot_has_permissions,
    error_handler,
    get_bot_admin_rights,
    group_management_command_enabled_check,
    is_user_admin,
)
from .state import _lock_label, load_group, save_group


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


def _check_entities(update: Update, entity_types) -> bool:
    """Helper to check for entities in a message or its caption."""
    if not update.message:
        return False

    if isinstance(entity_types, str):
        entity_types = (entity_types,)

    entities = getattr(update.message, 'entities', []) or []
    caption_entities = getattr(update.message, 'caption_entities', []) or []

    for entity in entities:
        if entity.type in entity_types:
            return True
    for entity in caption_entities:
        if entity.type in entity_types:
            return True
    return False


def _is_lock_triggered(
    lock_type: str,
    message,
    update: Update,
    text_or_caption: str,
    is_anonymous_channel_sender: bool,
    bots_joining: bool,
    is_forwarded_from_bot: bool,
    is_forwarded_from_channel: bool,
    is_forwarded_from_user: bool,
) -> bool:
    if lock_type == "album":
        return bool(getattr(message, 'media_group_id', None))
    if lock_type == "anonchannel":
        return is_anonymous_channel_sender
    if lock_type == "audio":
        return bool(getattr(message, 'audio', None))
    if lock_type == "bot":
        return bots_joining
    if lock_type == "botlink":
        return _check_entities(update, ("url", "text_link")) and "t.me/" in text_or_caption
    if lock_type == "cashtag":
        return _check_entities(update, "cashtag")
    if lock_type == "command":
        return _check_entities(update, "bot_command")
    if lock_type == "contact":
        return bool(getattr(message, 'contact', None))
    if lock_type == "document":
        return bool(getattr(message, 'document', None))
    if lock_type == "email":
        return _check_entities(update, "email")
    if lock_type == "emoji":
        return _check_entities(update, ("custom_emoji",))
    if lock_type == "forward":
        return bool(getattr(message, 'forward_date', None))
    if lock_type == "forwardbot":
        return is_forwarded_from_bot
    if lock_type == "forwardchannel":
        return is_forwarded_from_channel
    if lock_type == "forwarduser":
        return is_forwarded_from_user
    if lock_type == "game":
        return bool(getattr(message, 'game', None))
    if lock_type == "gif":
        return bool(getattr(message, 'animation', None))
    if lock_type == "inline":
        return bool(getattr(message, 'via_bot', None))
    if lock_type == "invitelink":
        return _check_entities(update, ("url", "text_link")) and (
            "t.me/joinchat/" in text_or_caption or "t.me/+" in text_or_caption
        )
    if lock_type == "location":
        return bool(getattr(message, 'location', None))
    if lock_type == "phone":
        return _check_entities(update, "phone_number")
    if lock_type == "photo":
        return bool(getattr(message, 'photo', None))
    if lock_type == "poll":
        return bool(getattr(message, 'poll', None))
    if lock_type == "spoiler":
        return _check_entities(update, "spoiler")
    if lock_type == "sticker":
        return bool(getattr(message, 'sticker', None) and not (
            getattr(message.sticker, "is_animated", False)
            or getattr(message.sticker, "is_video", False)
            or getattr(message.sticker, "is_premium", False)
        ))
    if lock_type == "stickeranimated":
        return bool(getattr(message, 'sticker', None) and (
            getattr(message.sticker, "is_animated", False)
            or getattr(message.sticker, "is_video", False)
        ))
    if lock_type == "stickerpremium":
        return bool(getattr(message, 'sticker', None) and getattr(message.sticker, "is_premium", False))
    if lock_type == "text":
        return bool(text_or_caption.strip())
    if lock_type == "url":
        return _check_entities(update, ("url", "text_link"))
    if lock_type == "video":
        return bool(getattr(message, 'video', None))
    if lock_type == "video_note":
        return bool(getattr(message, 'video_note', None))
    if lock_type == "voice":
        return bool(getattr(message, 'voice', None))
    return False


@error_handler
async def enforce_locks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id

    if await is_user_admin(context, chat_id, user_id):
        return

    group = await load_group(chat_id)
    locks = group.get("locks", {})

    should_delete = False

    try:
        message = update.message
        text_or_caption = getattr(message, 'text', None) or getattr(message, 'caption', None) or ""

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

        triggered_locks = []
        for lock_type, is_active in locks.items():
            if is_active and _is_lock_triggered(
                lock_type,
                message,
                update,
                text_or_caption,
                is_anonymous_channel_sender,
                bots_joining,
                is_forwarded_from_bot,
                is_forwarded_from_channel,
                is_forwarded_from_user,
            ):
                triggered_locks.append(lock_type)

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
        print(f"AttributeError in enforce_locks: {e}")
        triggered_locks = []
        should_delete = False
    except Exception as e:
        print(f"Unexpected error in enforce_locks: {e}")
        triggered_locks = []
        should_delete = False

    if should_delete:
        try:
            await update.message.delete()
        except Exception as e:
            print(f"Failed to delete locked message in chat {chat_id}: {e}")


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

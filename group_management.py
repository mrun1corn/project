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
    if os.path.exists(path):
        with open(path, 'r') as f:
            data = json.load(f)
            return data

    return {
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

def save_group(chat_id, data):
    with open(_group_file(chat_id), 'w') as f:
        json.dump(data, f, indent=4)

# --------------------- Decorators ---------------------

def admin_only(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status not in ('administrator', 'creator'):
                await update.message.reply_text("❌ You must be an admin to use this command.")
                return
        except Exception as e:
            await update.message.reply_text(f"❌ Error checking admin status: {e}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

def target_not_admin(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.message.reply_to_message:
            await update.message.reply_text("Please reply to a user's message.")
            return
        target_user_id = update.message.reply_to_message.from_user.id
        chat_id = update.effective_chat.id
        try:
            member = await context.bot.get_chat_member(chat_id, target_user_id)
            if member.status in ('administrator', 'creator'):
                await update.message.reply_text("👊 You cannot use this command on an admin.")
                return
        except Exception as e:
            await update.message.reply_text(f"❌ Error checking target's admin status: {e}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


# --------------------- Helper Functions ---------------------

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ('administrator', 'creator')
    except Exception:
        return False

def parse_time(time_str: str) -> int:
    """Converts a time string like '1d', '2h', '30m' to seconds."""
    if not time_str:
        return 0
    unit = time_str[-1].lower()
    value = int(time_str[:-1])
    if unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 3600
    elif unit == 'd':
        return value * 86400
    return 0

# --------------------- Core Features ---------------------

@admin_only
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    if not context.args:
        await update.message.reply_text(f"Welcome message:\n{group['welcome'] or 'disabled'}")
        return
    arg = " ".join(context.args)
    group['welcome'] = None if arg.lower() in ['off', 'no'] else arg
    await update.message.reply_text("✅ Welcome message disabled.")
    save_group(chat_id, group)
    
        
@admin_only
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    if not context.args:
        await update.message.reply_text(f"Goodbye message:\n{group['goodbye'] or 'disabled'}")
        return
    arg = " ".join(context.args)
    group['goodbye'] = None if arg.lower() in ['off', 'no'] else arg
    await update.message.reply_text("✅ Goodbye message disabled.")
    save_group(chat_id, group)


async def mention_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat.id
    group = load_group(chat_id)
    
    _, type, choice = query.data.split('_')
    
    mention_enabled = choice == 'yes'
    group[f'{type}_mention'] = mention_enabled
    save_group(chat_id, group)
    
    await query.edit_message_text(f"✅ User mentions for {type} message have been {'enabled' if mention_enabled else 'disabled'}.")

async def member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=msg)


async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=msg)

async def service_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    if group.get('action_delete', True) and update.effective_message:
        try:
            await update.effective_message.delete()
        except Exception:
            pass # Ignore if bot can't delete

@admin_only
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /filter <keyword> <reply>")
        return
    group = load_group(chat_id)
    trigger = context.args[0].lower()
    reply = " ".join(context.args[1:])
    group['filters'][trigger] = reply
    save_group(chat_id, group)
    await update.message.reply_text(f"✅ Filter added for '{trigger}'")

@admin_only
async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
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
@target_not_admin
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions=ChatPermissions(can_send_messages=False)
    )
    await update.message.reply_text("🔇 User muted.")

@admin_only
@target_not_admin
async def tmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.reply_to_message.from_user.id
    duration_str = context.args[0] if context.args else "1h"
    duration_sec = parse_time(duration_str)
    if duration_sec == 0:
        await update.message.reply_text("Invalid time format. Use 'm', 'h', or 'd'. E.g., /tmute 30m")
        return
    
    until_date = time.time() + duration_sec
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=int(until_date)
    )
    await update.message.reply_text(f"🔇 User muted for {duration_str}.")

@admin_only
async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to unmute them.")
        return
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
    )
    await update.message.reply_text("🔊 User unmuted.")

@admin_only
@target_not_admin
async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.reply_to_message.from_user.id
    chat_id = update.effective_chat.id
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        await context.bot.unban_chat_member(chat_id, user_id)
        await update.message.reply_text("👢 User kicked.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to kick user: {e}")

@admin_only
@target_not_admin
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.ban_chat_member(update.effective_chat.id, user_id)
    await update.message.reply_text("🚫 User banned.")

@admin_only
@target_not_admin
async def tban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.reply_to_message.from_user.id
    duration_str = context.args[0] if context.args else "1d"
    duration_sec = parse_time(duration_str)
    if duration_sec == 0:
        await update.message.reply_text("Invalid time format. Use 'm', 'h', or 'd'. E.g., /tban 2h")
        return
        
    until_date = time.time() + duration_sec
    await context.bot.ban_chat_member(update.effective_chat.id, user_id, until_date=int(until_date))
    await update.message.reply_text(f"🚫 User banned for {duration_str}.")

@admin_only
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        await context.bot.unban_chat_member(update.effective_chat.id, user_id)
        await update.message.reply_text("✅ User unbanned.")
    except (ValueError, IndexError):
        await update.message.reply_text("Usage: /unban <user_id>")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to unban user: {e}")

# --------------------- Warning System ---------------------

@admin_only
@target_not_admin
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    target_user = update.message.reply_to_message.from_user
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
async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to check their warnings.")
        return
    
    chat_id = update.effective_chat.id
    target_user = update.message.reply_to_message.from_user
    group = load_group(chat_id)
    
    count = group.get('warn_counts', {}).get(str(target_user.id), 0)
    await update.message.reply_text(f"User {target_user.mention_markdown_v2()} has {count} warnings.", parse_mode="MarkdownV2")

@admin_only
async def set_warn_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /warnlimit <number>")
        return
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    group['warn_limit'] = int(context.args[0])
    save_group(chat_id, group)
    await update.message.reply_text(f"✅ Warning limit set to {context.args[0]}.")

@admin_only
async def set_warn_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ['mute', 'kick', 'ban']:
        await update.message.reply_text("Usage: /warnmode <mute|kick|ban>")
        return
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    group['warn_mode'] = context.args[0].lower()
    save_group(chat_id, group)
    await update.message.reply_text(f"✅ Warning mode set to {context.args[0].lower()}.")


# --------------------- Group Settings ---------------------

LOCKABLE_TYPES = ["gif", "sticker", "photo", "video", "audio", "voice", "document", "text", "emoji"]

@admin_only
async def lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    locks = group.setdefault("locks", {})

    if not context.args:
        enabled = ", ".join([k for k, v in locks.items() if v])
        await update.message.reply_text(f"🔒 Enabled locks: {enabled or 'None'}\nAvailable: {', '.join(LOCKABLE_TYPES)}")
        return

    arg = context.args[0].lower()
    if arg == "all":
        for lock_type in LOCKABLE_TYPES:
            locks[lock_type] = True
        await update.message.reply_text("✅ All features locked.")
    elif arg in LOCKABLE_TYPES:
        locks[arg] = True
        await update.message.reply_text(f"✅ Locked {arg}.")
    else:
        await update.message.reply_text(f"Usage: /lock <{'|'.join(LOCKABLE_TYPES)}|all>")
    save_group(chat_id, group)

@admin_only
async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    locks = group.setdefault("locks", {})

    if not context.args:
        await update.message.reply_text(f"Usage: /unlock <{'|'.join(LOCKABLE_TYPES)}|all>")
        return

    arg = context.args[0].lower()
    if arg == "all":
        for lock_type in LOCKABLE_TYPES:
            locks[lock_type] = False
        await update.message.reply_text("✅ All features unlocked.")
    elif arg in LOCKABLE_TYPES:
        locks[arg] = False
        await update.message.reply_text(f"✅ Unlocked {arg}.")
    else:
        await update.message.reply_text(f"Usage: /unlock <{'|'.join(LOCKABLE_TYPES)}|all>")
    save_group(chat_id, group)

@admin_only
async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notify = 'loud' in context.args
    
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
        
    try:
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

async def action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
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

@admin_only
@target_not_admin
async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.reply_to_message.from_user.id
    chat_id = update.effective_chat.id
    custom_title = " ".join(context.args) if context.args else "Admin"

    try:
        await context.bot.promote_chat_member(
            chat_id=chat_id, user_id=user_id, **MINIMAL_ADMIN_RIGHTS.to_dict()
        )
        await context.bot.set_chat_administrator_custom_title(chat_id, user_id, custom_title)
        await update.message.reply_text(f"✅ Promoted with title: {custom_title}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to promote: {e}")

@admin_only
async def permission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        # Display available permissions
        available_perms = ", ".join(PERMISSION_MAP.keys())
        await update.message.reply_text(f"Available permissions: {available_perms}\nUsage: /permission <type> (reply to user)")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to modify their permissions.")
        return

    perm_key = context.args[0].lower()
    if perm_key not in PERMISSION_MAP:
        await update.message.reply_text(f"❌ Unknown permission. Allowed: {', '.join(PERMISSION_MAP.keys())}")
        return

    permission_name = PERMISSION_MAP[perm_key]
    user_id = update.message.reply_to_message.from_user.id

    try:
        # Fetch current admin rights
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in ('administrator', 'creator'):
            await update.message.reply_text("❌ User is not an admin.")
            return

        # Get current rights, or start with minimal if none exist
        current_rights = member.custom_admin_rights
        if not current_rights:
            current_rights = MINIMAL_ADMIN_RIGHTS

        # Update only the specified permission
        rights_dict = current_rights.to_dict()
        rights_dict[permission_name] = True
        
        new_rights = ChatAdministratorRights(**rights_dict)

        await context.bot.promote_chat_member(chat_id, user_id, **new_rights.to_dict())
        await update.message.reply_text(f"✅ Granted `{perm_key}` permission.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to update permission: {e}")

@admin_only
async def demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to demote them.")
        return
        
    user_id = update.message.reply_to_message.from_user.id
    chat_id = update.effective_chat.id

    try:
        # Create a rights object with all False values
        demote_rights = ChatAdministratorRights.from_defaults()
        await context.bot.promote_chat_member(chat_id, user_id, **demote_rights.to_dict())
        await update.message.reply_text("⬇️ User demoted.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to demote: {e}")

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
    save_group(chat_id, group)

@admin_only
async def call_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    members = group.get('members', {})
    
    if not members:
        await update.message.reply_text("No active members recorded yet. Let people chat first.")
        return

    mention_text = " ".join(f"@{username}" for username in members.values() if username)
    reason = " ".join(context.args)
    
    if not mention_text:
        await update.message.reply_text("No members with usernames found to mention.")
        return

    message = f"📣 **Calling all members!**\n{reason}\n\n{mention_text}"
    await update.message.reply_text(message, parse_mode="Markdown")


# --------------------- Registration ---------------------

def register_group_management(app):
    # Welcome/Goodbye
    app.add_handler(CommandHandler("welcome", welcome))
    app.add_handler(CommandHandler("goodbye", goodbye))
    app.add_handler(CallbackQueryHandler(mention_callback, pattern="^mention_"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, member_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))
    
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
    app.add_handler(CommandHandler("lock", lock))
    app.add_handler(CommandHandler("unlock", unlock))
    app.add_handler(CommandHandler("pin", pin))
    app.add_handler(CommandHandler("action", action_toggle))
    app.add_handler(CallbackQueryHandler(action_callback, pattern="^action_set_"))

    # Admin Roles
    app.add_handler(CommandHandler("promote", promote))
    app.add_handler(CommandHandler("demote", demote))
    app.add_handler(CommandHandler("permission", permission))

    # Utility
    app.add_handler(CommandHandler("call", call_all))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, update_member_list), group=1) # Lower priority

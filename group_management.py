import os
import json
import time
from asyncio import sleep
from telegram import Update, ChatPermissions, ChatAdministratorRights
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

GROUP_DATA_DIR = 'group_data'
os.makedirs(GROUP_DATA_DIR, exist_ok=True)

def _group_file(chat_id):
    return os.path.join(GROUP_DATA_DIR, f"{chat_id}.json")

def load_group(chat_id):
    path = _group_file(chat_id)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {
        'welcome': None,
        'goodbye': None,
        'filters': {},
        'warn_counts': {},
        'warn_limit': 3,
        'warn_mode': 'mute',
        'locks': {}
    }

MINIMAL_ADMIN_RIGHTS = ChatAdministratorRights(
    can_manage_chat=True,  # Basic admin access
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

PERMISSION_MAP = {
    'delete': 'can_delete_messages',
    'restrict': 'can_restrict_members',
    'pin': 'can_pin_messages',
    'video': 'can_manage_video_chats',
    'info': 'can_change_info',
    'invite': 'can_invite_users',
    'promote': 'can_promote_members',
    'anonymous': 'is_anonymous',
    'topics': 'can_manage_topics',
    'post_stories': 'can_post_stories',
    'edit_stories': 'can_edit_stories',
    'delete_stories': 'can_delete_stories'
}
def save_group(chat_id, data):
    with open(_group_file(chat_id), 'w') as f:
        json.dump(data, f)

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ('administrator', 'creator')
    except Exception:
        return False

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to use this command.")
        return
    group = load_group(chat_id)
    if not context.args:
        await update.message.reply_text(f"Welcome message:\n{group['welcome'] or 'disabled'}")
        return
    arg = " ".join(context.args)
    group['welcome'] = None if arg.lower() in ['off', 'no'] else arg
    save_group(chat_id, group)
    await update.message.reply_text("✅ Welcome message updated.")

async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to use this command.")
        return
    group = load_group(chat_id)
    if not context.args:
        await update.message.reply_text(f"Goodbye message:\n{group['goodbye'] or 'disabled'}")
        return
    arg = " ".join(context.args)
    group['goodbye'] = None if arg.lower() in ['off', 'no'] else arg
    save_group(chat_id, group)
    await update.message.reply_text("✅ Goodbye message updated.")

async def member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    msg = group.get("welcome")
    if not msg:
        return
    for m in update.message.new_chat_members:
        try:
            formatted = msg.format(
                first=m.first_name or "",
                fullname=f"{m.first_name or ''} {m.last_name or ''}".strip(),
                username=m.username or "",
                mention=m.mention_markdown_v2(),
                chatname=update.effective_chat.title or ""
            )
            await update.message.reply_text(formatted, parse_mode="MarkdownV2")
        except Exception:
            await update.message.reply_text(msg)

async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    msg = group.get("goodbye")
    if not msg:
        return
    m = update.message.left_chat_member
    try:
        formatted = msg.format(
            first=m.first_name or "",
            fullname=f"{m.first_name or ''} {m.last_name or ''}".strip(),
            username=m.username or "",
            mention=m.mention_markdown_v2(),
            chatname=update.effective_chat.title or ""
        )
        await update.message.reply_text(formatted, parse_mode="MarkdownV2")
    except Exception:
        await update.message.reply_text(msg)

async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to add filters.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /filter <keyword> <reply>")
        return
    group = load_group(chat_id)
    trigger = context.args[0].lower()
    reply = " ".join(context.args[1:])
    group['filters'][trigger] = reply
    save_group(chat_id, group)
    await update.message.reply_text(f"✅ Filter added for '{trigger}'")

async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to remove filters.")
        return
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
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    group = load_group(chat_id)
    for trigger, reply in group.get("filters", {}).items():
        if trigger in text:
            await update.message.reply_text(reply)
            break

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to mute users.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to mute them.")
        return
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions=ChatPermissions(can_send_messages=False)
    )
    await update.message.reply_text("🔇 User muted.")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to unmute users.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to unmute them.")
        return
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions=ChatPermissions(can_send_messages=True)
    )
    await update.message.reply_text("🔊 User unmuted.")

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to kick users.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to kick them.")
        return

    user_id = update.message.reply_to_message.from_user.id
    chat_id = update.effective_chat.id

    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        await context.bot.unban_chat_member(chat_id, user_id)  # unban immediately to make it a "kick"
        await update.message.reply_text("👢 User kicked.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to kick user: {e}")


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to ban users.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to ban them.")
        return
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.ban_chat_member(update.effective_chat.id, user_id)
    await update.message.reply_text("🚫 User banned.")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to unban users.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        await context.bot.unban_chat_member(update.effective_chat.id, user_id)
        await update.message.reply_text("✅ User unbanned.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to unban user: {e}")

LOCKABLE_TYPES = [
    "gif", "sticker", "photo", "video", "audio", "voice", "document", "text", "emoji"
]

async def lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    locks = group.setdefault("locks", {})

    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to use this command.")
        return

    if not context.args:
        if not locks:
            await update.message.reply_text("🔒 No locks enabled.\nAvailable locks: " + ", ".join(LOCKABLE_TYPES))
            return
        enabled = ", ".join([k for k, v in locks.items() if v])
        await update.message.reply_text(f"🔒 Enabled locks: {enabled or 'None'}")
        return

    arg = context.args[0].lower()
    if arg == "all":
        for lock in LOCKABLE_TYPES:
            locks[lock] = True
        save_group(chat_id, group)
        await update.message.reply_text("✅ All features locked.")
    elif arg in LOCKABLE_TYPES:
        locks[arg] = True
        save_group(chat_id, group)
        await update.message.reply_text(f"✅ Locked {arg}.")
    else:
        await update.message.reply_text("Usage: /lock <" + "|".join(LOCKABLE_TYPES) + "|all>")

async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group = load_group(chat_id)
    locks = group.setdefault("locks", {})

    if not await is_admin(update, context):
        await update.message.reply_text("❌ You must be an admin to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /unlock <" + "|".join(LOCKABLE_TYPES) + "|all>")
        return

    arg = context.args[0].lower()
    if arg == "all":
        for lock in LOCKABLE_TYPES:
            locks[lock] = False
        save_group(chat_id, group)
        await update.message.reply_text("✅ All features unlocked.")
    elif arg in LOCKABLE_TYPES:
        locks[arg] = False
        save_group(chat_id, group)
        await update.message.reply_text(f"✅ Unlocked {arg}.")
    else:
        await update.message.reply_text("Usage: /unlock <" + "|".join(LOCKABLE_TYPES) + "|all>")

async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Only admins can promote.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to promote them.")
        return

    user_id = update.message.reply_to_message.from_user.id
    chat_id = update.effective_chat.id
    custom_title = " ".join(context.args) if context.args else "admin"  # Default title

    try:
        # Promote with minimal rights
        await context.bot.promote_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            **MINIMAL_ADMIN_RIGHTS.to_dict()
        )
        # Set custom title
        await context.bot.set_chat_administrator_custom_title(chat_id, user_id, custom_title)
        await update.message.reply_text(f"✅ Promoted with title: {custom_title}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to promote: {e}")

async def permission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Only admins can modify permissions.")
        return

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

        # Update only the specified permission
        rights = ChatAdministratorRights(**member.custom_admin_rights.to_dict())
        setattr(rights, permission_name, True)
        await context.bot.promote_chat_member(chat_id, user_id, **rights.to_dict())
        await update.message.reply_text(f"✅ Granted `{perm_key}` permission.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to update permission: {e}")

async def demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Only admins can demote.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to demote them.")
        return

    user_id = update.message.reply_to_message.from_user.id
    chat_id = update.effective_chat.id

    try:
        await context.bot.promote_chat_member(
            chat_id,
            user_id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            is_anonymous=False
        )
        await update.message.reply_text("⬇️ User demoted.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to demote: {e}")

def register_group_management(app):
    app.add_handler(CommandHandler("welcome", welcome))
    app.add_handler(CommandHandler("goodbye", goodbye))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, member_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))
    app.add_handler(CommandHandler("filter", add_filter))
    app.add_handler(CommandHandler("stop", remove_filter))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_responder))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("lock", lock))
    app.add_handler(CommandHandler("unlock", unlock))
    app.add_handler(CommandHandler("promote", promote))
    app.add_handler(CommandHandler("permission", permission))
    app.add_handler(CommandHandler("demote", demote))

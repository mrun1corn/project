from telegram import ChatAdministratorRights

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

MINIMAL_ADMIN_RIGHTS = ChatAdministratorRights(
    can_manage_chat=True, can_delete_messages=False, can_manage_video_chats=False,
    can_restrict_members=False, can_promote_members=False, can_change_info=False,
    can_invite_users=False, can_pin_messages=False, is_anonymous=False,
    can_manage_topics=False, can_post_stories=False, can_edit_stories=False,
    can_delete_stories=False
)

PERMISSION_MAP = {
    'delete': 'can_delete_messages', 'restrict': 'can_restrict_members',
    'pin': 'can_pin_messages', 'video': 'can_manage_video_chats',
    'info': 'can_change_info', 'invite': 'can_invite_users',
    'promote': 'can_promote_members', 'anonymous': 'is_anonymous',
    'topics': 'can_manage_topics', 'post_stories': 'can_post_stories',
    'edit_stories': 'can_edit_stories', 'delete_stories': 'can_delete_stories'
}

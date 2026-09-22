from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

# Re-export all sub-module symbols for full backward compatibility
from .constants import (
    ADMIN_ONLY_MSG,
    ADMIN_PERMISSION_MSG,
    BOT_NO_CHANGE_INFO_PERMISSION_MSG,
    BOT_NO_DELETE_MESSAGES_PERMISSION_MSG,
    BOT_NO_DELETE_PERMISSION_MSG,
    BOT_NO_INVITE_USERS_PERMISSION_MSG,
    BOT_NO_MANAGE_TOPICS_PERMISSION_MSG,
    BOT_NO_PIN_MESSAGES_PERMISSION_MSG,
    BOT_NO_PROMOTE_PERMISSION_MSG,
    BOT_NO_RESTRICT_PERMISSION_MSG,
    DEFAULT_GROUP_DATA,
    INVALID_TIME_FORMAT_MSG,
    LOCK_KEY_ALIASES,
    LOCK_LABELS,
    LOCKABLE_TYPES,
    MINIMAL_ADMIN_RIGHTS,
    NO_ADMIN_BAN_MSG,
    NO_ADMIN_KICK_MSG,
    NO_ADMIN_MUTE_BAN_MSG,
    NO_ADMIN_TBAN_MSG,
    NO_ADMIN_WARN_MSG,
    NO_USERNAME_ADMINS_MSG,
    PERMISSION_MAP,
    REPLY_TO_USER_MSG,
    USAGE_FILTER_MSG,
    USAGE_PIN_MSG,
    USAGE_PURGE_MSG,
    USAGE_STOP_MSG,
    USAGE_UNBAN_MSG,
    USAGE_WARN_LIMIT_MSG,
    USAGE_WARN_MODE_MSG,
    USER_NO_LONGER_ADMIN_MSG,
    USER_NOT_ADMIN_PROMOTE_FIRST_MSG,
)
from .filters import (
    add_filter,
    filter_responder,
    remove_filter,
)
from .greetings import (
    _format_member_message,
    goodbye,
    member_join,
    member_left,
    mention_callback,
    service_message_handler,
    welcome,
)
from .locks import (
    _build_locks_keyboard,
    _check_entities,
    _is_lock_triggered,
    action_callback,
    action_toggle,
    enforce_locks,
    locks,
    locks_callback,
)
from .management import (
    _build_group_manage_keyboard,
    _build_permissions_keyboard,
    demote,
    group_manage_callback,
    group_manage_command,
    permissions,
    permissions_callback,
    pin,
    promote,
    tagadmin,
    update_member_list,
)
from .moderation import (
    ban,
    kick,
    mute,
    parse_time,
    purge,
    set_warn_limit,
    set_warn_mode,
    tban,
    tmute,
    unban,
    unmute,
    warn,
    warns,
)
from .permissions import (
    _admin_cache,
    _cache_admin_status,
    _chat_admin_rights_to_dict,
    admin_only,
    bot_has_permissions,
    error_handler,
    get_bot_admin_rights,
    group_management_command_enabled_check,
    is_user_admin,
)
from .state import (
    GROUP_COMMANDS,
    GROUP_COMMANDS_COLLECTION,
    GROUPS_COLLECTION,
    _group_cache,
    _lock_label,
    _normalize_locks,
    load_group,
    load_group_command_states,
    save_group,
    save_group_command_states,
)
from src.core.fallback import load_json, save_json


def register_group_management(app):
    # Welcome/Goodbye
    app.add_handler(CommandHandler("welcome", welcome))
    app.add_handler(CommandHandler("goodbye", goodbye))
    app.add_handler(CallbackQueryHandler(mention_callback, pattern="^mention_"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, member_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, enforce_locks), group=-2)

    # Service message handler for auto-deletion
    app.add_handler(MessageHandler(filters.StatusUpdate.ALL, service_message_handler), group=-1)

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, update_member_list), group=1)

    # Group Management Commands
    app.add_handler(CommandHandler("group_manage", group_manage_command))
    app.add_handler(CallbackQueryHandler(group_manage_callback, pattern="^group_manage_"))

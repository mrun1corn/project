import time
from functools import wraps
from telegram import ChatAdministratorRights, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .constants import (
    ADMIN_ONLY_MSG,
    MINIMAL_ADMIN_RIGHTS,
)
from .state import load_group_command_states

_MAX_ADMIN_CACHE_SIZE = 2000
_ADMIN_CACHE_TIMEOUT = 60  # seconds
_admin_cache: dict[tuple[int, int], tuple[bool, float]] = {}


def _cache_admin_status(chat_id: int, user_id: int, is_admin: bool) -> None:
    now = time.time()
    if len(_admin_cache) >= _MAX_ADMIN_CACHE_SIZE:
        expired_keys = [k for k, v in _admin_cache.items() if now - v[1] > _ADMIN_CACHE_TIMEOUT]
        for k in expired_keys:
            _admin_cache.pop(k, None)
        while len(_admin_cache) >= _MAX_ADMIN_CACHE_SIZE:
            first_key = next(iter(_admin_cache))
            _admin_cache.pop(first_key, None)
    _admin_cache[(chat_id, user_id)] = (is_admin, now)


async def is_user_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    """Checks if a user is an administrator in the chat."""
    cache_key = (chat_id, user_id)
    cached = _admin_cache.get(cache_key)
    if cached and (time.time() - cached[1] < _ADMIN_CACHE_TIMEOUT):
        return cached[0]

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        is_admin = member.status in ['administrator', 'creator']
        _cache_admin_status(chat_id, user_id, is_admin)
        return is_admin
    except Exception as e:
        print(f"Error checking admin status for chat {chat_id}, user {user_id}: {e}")
        return False


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

    return ChatAdministratorRights(
        can_manage_chat=False, can_delete_messages=False, can_manage_video_chats=False,
        can_restrict_members=False, can_promote_members=False, can_change_info=False,
        can_invite_users=False, can_pin_messages=False, is_anonymous=False,
        can_manage_topics=False, can_post_stories=False, can_edit_stories=False,
        can_delete_stories=False
    )


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

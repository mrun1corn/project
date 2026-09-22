from telegram import ChatAdministratorRights, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src.core.config import settings
from src.core.ui import build_toggle_keyboard
from .constants import (
    ADMIN_PERMISSION_MSG,
    MINIMAL_ADMIN_RIGHTS,
    NO_USERNAME_ADMINS_MSG,
    PERMISSION_MAP,
    REPLY_TO_USER_MSG,
    USAGE_PIN_MSG,
    USER_NO_LONGER_ADMIN_MSG,
    USER_NOT_ADMIN_PROMOTE_FIRST_MSG,
)
from .permissions import (
    _chat_admin_rights_to_dict,
    admin_only,
    bot_has_permissions,
    error_handler,
    get_bot_admin_rights,
    group_management_command_enabled_check,
    is_user_admin,
)
from .state import load_group, load_group_command_states, save_group_command_states


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


@admin_only
@group_management_command_enabled_check("pin")
@bot_has_permissions(["can_pin_messages"])
@error_handler
async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notify = 'loud' in context.args

    if update.message.reply_to_message:
        message_id = update.message.reply_to_message.message_id
    elif context.args:
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

    for right, value in promotable_rights.items():
        if value and not getattr(bot_rights, right, False):
            promotable_rights[right] = False

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

    updated_rights_dict = _chat_admin_rights_to_dict(MINIMAL_ADMIN_RIGHTS)
    for perm_key_map, perm_name_map in PERMISSION_MAP.items():
        updated_rights_dict[perm_name_map] = getattr(member, perm_name_map, False)

    updated_rights_dict[permission_name] = not updated_rights_dict.get(permission_name, False)

    for right, value in updated_rights_dict.items():
        if value and not getattr(bot_rights, right, False):
            updated_rights_dict[right] = False

    new_rights = ChatAdministratorRights(**updated_rights_dict)

    await context.bot.promote_chat_member(chat_id, target_user_id, **_chat_admin_rights_to_dict(new_rights))

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

    demote_rights = {attr: False for attr in _chat_admin_rights_to_dict(MINIMAL_ADMIN_RIGHTS).keys()}
    await context.bot.promote_chat_member(
        chat_id=chat_id,
        user_id=target_user_id,
        **demote_rights
    )
    await update.message.reply_text("User demoted.")


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


@group_management_command_enabled_check("tagadmin")
@error_handler
async def tagadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    def escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    chat_id = update.effective_chat.id
    admins = await context.bot.get_chat_administrators(chat_id)

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

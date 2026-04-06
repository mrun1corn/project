from __future__ import annotations

from dataclasses import dataclass

from telegram import Update

from comm_checker import check_command_enabled, check_user_approval
from settings import settings


@dataclass(frozen=True)
class CommandSpec:
    name: str
    usage: str | None = None
    requires_approval: bool = True
    admin_only: bool = False
    disabled_message: str | None = None
    approval_message: str = "⚠️ You are not approved to use this command yet."
    admin_message: str = "🔒 You do not have permission to use this command."


async def guard_command(update: Update, spec: CommandSpec, *, require_args: bool = False) -> bool:
    message = update.effective_message
    user = update.effective_user

    if spec.admin_only and user.id != settings.admin_chat_id:
        await message.reply_text(spec.admin_message)
        return False

    if spec.requires_approval and user.id != settings.admin_chat_id:
        if not await check_user_approval(user.id):
            await message.reply_text(spec.approval_message)
            return False

    if not await check_command_enabled(spec.name) and user.id != settings.admin_chat_id:
        await message.reply_text(spec.disabled_message or f"⚠️ {spec.name.capitalize()} is currently disabled.")
        return False

    if require_args:
        text = message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2 and spec.usage:
            await message.reply_text(spec.usage)
            return False

    return True

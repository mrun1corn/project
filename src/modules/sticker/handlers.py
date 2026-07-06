from __future__ import annotations

import html
import os

import aiofiles
from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputSticker, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from src.core.security import check_command_enabled
from src.core.config import settings


def get_file_extension(sticker_format: str) -> str:
    return {
        "video": ".webm",
        "animated": ".tgs",
        "static": ".png",
    }.get(sticker_format, ".png")


async def process_static_image(temp_name: str) -> bytes:
    processed_name = None
    try:
        processed_name = f"{temp_name}_processed.png"
        with Image.open(temp_name).convert("RGBA") as image:
            max_size = 512
            scale = max_size / max(image.width, image.height)
            new_size = (int(image.width * scale), int(image.height * scale))
            resized = image.resize(new_size, Image.Resampling.LANCZOS)

            canvas = Image.new("RGBA", (max_size, max_size), (0, 0, 0, 0))
            paste_x = (max_size - resized.width) // 2
            paste_y = (max_size - resized.height) // 2
            canvas.paste(resized, (paste_x, paste_y))
            canvas.save(processed_name, format="PNG")

        if os.path.getsize(processed_name) > 512 * 1024:
            raise ValueError("Sticker size exceeds Telegram's 512 KB limit.")

        async with aiofiles.open(processed_name, "rb") as processed_file:
            return await processed_file.read()
    finally:
        for candidate in (temp_name, processed_name):
            if candidate and os.path.exists(candidate):
                os.remove(candidate)


async def get_sticker_data(telegram_file, sticker_format: str, temp_name: str) -> bytes:
    await telegram_file.download_to_drive(temp_name)
    if sticker_format == "static":
        return await process_static_image(temp_name)

    try:
        async with aiofiles.open(temp_name, "rb") as source_file:
            return await source_file.read()
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def create_pack_name(user, bot_username: str, sticker_format: str, count: int = 1) -> tuple[str, str]:
    base_name = user.username.lower() if user.username and user.username[0].isalpha() else f"u{user.id}"
    animated_pack = sticker_format in {"animated", "video"}
    suffix = "_animated" if animated_pack else ""
    pack_name = f"{base_name}{suffix}_by_{bot_username}" if count == 1 else f"{base_name}{suffix}_by_{bot_username}_{count}"
    pack_title = f"{user.first_name or 'User'}'s {'Animated ' if animated_pack else ''}Stickers"
    if count > 1:
        pack_title = f"{pack_title} {count}"
    return pack_name, pack_title


async def kang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    bot = context.bot
    message = update.effective_message
    bot_username = bot.username.lstrip("@").lower()

    if user.id != settings.admin_chat_id and not await check_command_enabled("kang"):
        await message.reply_text(
            "<b>Sticker Tool Unavailable</b>\nThis command is currently disabled.",
            parse_mode="HTML",
        )
        return

    if not message.reply_to_message:
        await message.reply_text(
            "<b>How To Use</b>\nReply to an image or sticker with <code>/kang</code> to add it to your sticker pack.",
            parse_mode="HTML",
        )
        return

    reply = message.reply_to_message
    file_id = None
    sticker_format = "static"

    if reply.sticker:
        file_id = reply.sticker.file_id
        sticker_format = "video" if reply.sticker.is_video else "animated" if reply.sticker.is_animated else "static"
    elif reply.photo:
        file_id = reply.photo[-1].file_id
    elif reply.document and (reply.document.mime_type or "").startswith("image/"):
        file_id = reply.document.file_id
    else:
        await message.reply_text(
            "<b>Unsupported Reply</b>\nReply to an image or sticker to continue.",
            parse_mode="HTML",
        )
        return

    telegram_file = await bot.get_file(file_id)
    if telegram_file.file_size and telegram_file.file_size > 20 * 1024 * 1024:
        await message.reply_text(
            "<b>File Too Large</b>\nThe maximum supported size is <code>20 MB</code>.",
            parse_mode="HTML",
        )
        return

    emoji = "".join(context.args) if context.args else (reply.sticker.emoji if reply.sticker and reply.sticker.emoji else "🙂")
    progress = await message.reply_text(
        "<b>Sticker Pack Wizard</b>\n🎨 Preparing your sticker.",
        parse_mode="HTML",
    )

    try:
        suffix = get_file_extension(sticker_format)
        temp_name = f"downloads/kang_{user.id}_{telegram_file.file_unique_id}{suffix}"
        os.makedirs("downloads", exist_ok=True)
        sticker_data = await get_sticker_data(telegram_file, sticker_format, temp_name)

        pack_count = 1
        pack_name, pack_title = create_pack_name(user, bot_username, sticker_format)
        sticker = InputSticker(sticker=sticker_data, emoji_list=[emoji], format=sticker_format)

        while True:
            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("View Pack", url=f"https://t.me/addstickers/{pack_name}")]]
            )
            try:
                await bot.add_sticker_to_set(user_id=user.id, name=pack_name, sticker=sticker)
                await progress.edit_text(
                    f"<b>Sticker Added</b>\n✨ Type: <code>{html.escape(sticker_format)}</code>\n😀 Emoji: {html.escape(emoji)}\nOpen the pack below to view it.",
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                return
            except BadRequest as exc:
                error_text = str(exc).lower()
                if "stickerset_invalid" in error_text or "not found" in error_text:
                    try:
                        await bot.create_new_sticker_set(
                            user_id=user.id,
                            name=pack_name,
                            title=pack_title,
                            stickers=[sticker],
                        )
                        await progress.edit_text(
                            f"<b>New Pack Created</b>\n✨ Type: <code>{html.escape(sticker_format)}</code>\n😀 Emoji: {html.escape(emoji)}\nOpen the pack below to view it.",
                            parse_mode="HTML",
                            reply_markup=reply_markup,
                        )
                        return
                    except BadRequest as create_error:
                        if "peer_id_invalid" in str(create_error).lower():
                            await progress.edit_text(
                                "<b>Private Chat Required</b>\nPlease start the bot in a private chat with <code>/start</code> and try again.",
                                parse_mode="HTML",
                            )
                        else:
                            await progress.edit_text(
                                f"<b>Pack Creation Failed</b>\n<code>{html.escape(str(create_error))}</code>",
                                parse_mode="HTML",
                            )
                        return
                if "stickers_too_much" in error_text or "set_full" in error_text:
                    pack_count += 1
                    pack_name, pack_title = create_pack_name(user, bot_username, sticker_format, pack_count)
                    continue
                if "invalid sticker emoji" in error_text:
                    await progress.edit_text(
                        f"<b>Invalid Emoji</b>\n<code>{html.escape(emoji)}</code> is not supported. Try a standard emoji like 🙂.",
                        parse_mode="HTML",
                    )
                    return
                if "sticker_invalid" in error_text:
                    await progress.edit_text(
                        "<b>Invalid Sticker Format</b>\nUse PNG, JPG, TGS, or WEBM input.",
                        parse_mode="HTML",
                    )
                    return
                await progress.edit_text(
                    f"<b>Failed To Add Sticker</b>\n<code>{html.escape(str(exc))}</code>",
                    parse_mode="HTML",
                )
                return
            except TelegramError as exc:
                await progress.edit_text(
                    f"<b>Telegram Error</b>\n<code>{html.escape(str(exc))}</code>\nPlease try again later.",
                    parse_mode="HTML",
                )
                return
    except ValueError as exc:
        await progress.edit_text(
            f"<b>Sticker Validation Failed</b>\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )
    except Exception as exc:
        await progress.edit_text(
            f"<b>Sticker Creation Failed</b>\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )

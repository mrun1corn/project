import os
import asyncio
from tempfile import NamedTemporaryFile
from telegram import Update, InputSticker, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest
from PIL import Image
import aiofiles
from config import ADMIN_CHAT_ID
from comm_checker import command_states

def escape_markdown_v2(text: str) -> str:
    """Escape reserved characters for Telegram MarkdownV2."""
    reserved_chars = r'_[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in reserved_chars else char for char in text)

async def get_file_extension(sticker_format: str) -> str:
    """Determine file extension based on sticker format."""
    return {
        "video": ".webm",
        "animated": ".tgs",
        "static": ".png"
    }.get(sticker_format, ".png")

async def process_static_image(temp_name: str) -> bytes:
    """Process static image to meet Telegram sticker requirements."""
    try:
        async with aiofiles.tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            with Image.open(temp_name).convert("RGBA") as im:
                max_size = 512
                scale = max_size / max(im.width, im.height)
                new_size = (int(im.width * scale), int(im.height * scale))
                im = im.resize(new_size, Image.Resampling.LANCZOS)

                new_im = Image.new("RGBA", (max_size, max_size), (0, 0, 0, 0))
                paste_x = (max_size - im.width) // 2
                paste_y = (max_size - im.height) // 2
                new_im.paste(im, (paste_x, paste_y))
                new_im.save(tmp.name, format="PNG")

                if os.path.getsize(tmp.name) > 512 * 1024:
                    raise ValueError("Sticker size exceeds 512KB limit")

                async with aiofiles.open(tmp.name, "rb") as f:
                    return await f.read()
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)

async def get_sticker_data(tg_file, sticker_format: str, temp_name: str) -> bytes:
    """Download and process sticker data."""
    await tg_file.download_to_drive(temp_name)
    if sticker_format == "static":
        return await process_static_image(temp_name)
    async with aiofiles.open(temp_name, "rb") as f:
        return await f.read()

async def create_pack_name(user, bot_username: str, sticker_format: str, count: int = 1) -> tuple[str, str]:
    """Generate sticker pack name and title based on sticker format."""
    base_name = user.username.lower() if user.username and user.username[0].isalpha() else f"u{user.id}"
    is_animated = sticker_format in ["animated", "video"]
    suffix = "_animated" if is_animated else ""
    pack_name = f"{base_name}{suffix}_by_{bot_username}" if count == 1 else f"{base_name}{suffix}_by_{bot_username}_{count}"
    pack_title = f"{user.first_name or 'User'}'s {'Animated ' if is_animated else ''}Stickers" if count == 1 else f"{user.first_name or 'User'}'s {'Animated ' if is_animated else ''}Stickers {count}"
    return pack_name, pack_title

async def kang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /kang command to create or add to a sticker pack."""
    user = update.effective_user
    bot = context.bot
    msg = update.effective_message
    bot_username = bot.username.lstrip('@').lower()

    if user.id != ADMIN_CHAT_ID and not command_states.get('kang', True):
        await msg.reply_text(
            escape_markdown_v2("❌ Kang command is disabled."),
            parse_mode="MarkdownV2"
        )
        return

    if not msg.reply_to_message:
        await msg.reply_text(
            escape_markdown_v2("❌ Reply to an image or sticker with /kang"),
            parse_mode="MarkdownV2"
        )
        return

    reply = msg.reply_to_message
    file_id = None
    sticker_format = "static"

    # Detect content type and set sticker format
    if reply.sticker:
        file_id = reply.sticker.file_id
        sticker_format = "video" if reply.sticker.is_video else "animated" if reply.sticker.is_animated else "static"
    elif reply.photo:
        file_id = reply.photo[-1].file_id
    elif reply.document and (reply.document.mime_type or "").startswith("image/"):
        file_id = reply.document.file_id
    else:
        await msg.reply_text(
            escape_markdown_v2("❌ Reply to an image or sticker"),
            parse_mode="MarkdownV2"
        )
        return

    # Early file size validation
    tg_file = await bot.get_file(file_id)
    if tg_file.file_size > 20 * 1024 * 1024:
        await msg.reply_text(
            escape_markdown_v2("❌ File too large. Max 20MB"),
            parse_mode="MarkdownV2"
        )
        return

    # Get emoji
    emoji = (
        "".join(context.args)
        if context.args
        else (reply.sticker.emoji if reply.sticker and reply.sticker.emoji else "😄")
    )

    progress = await msg.reply_text(
        escape_markdown_v2("⏳ Creating sticker..."),
        parse_mode="MarkdownV2"
    )

    try:
        # Download and process file
        suffix = await get_file_extension(sticker_format)
        async with aiofiles.tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            sticker_data = await get_sticker_data(tg_file, sticker_format, tmp.name)

        # Prepare sticker pack
        pack_count = 1
        pack_name, pack_title = await create_pack_name(user, bot_username, sticker_format)
        sticker = InputSticker(sticker=sticker_data, emoji_list=[emoji], format=sticker_format)
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("View Pack", url=f"https://t.me/addstickers/{pack_name}")]])

        # Try adding or creating sticker pack
        while True:
            try:
                await bot.add_sticker_to_set(user_id=user.id, name=pack_name, sticker=sticker)
                await progress.edit_text(
                    escape_markdown_v2(
                        f"✅ Added {sticker_format} sticker with emoji {emoji}\n"
                        f"📌 Reopen pack to see it"
                    ),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
                break
            except BadRequest as e:
                err = str(e).lower()
                if "stickerset_invalid" in err or "not found" in err:
                    try:
                        await bot.create_new_sticker_set(
                            user_id=user.id,
                            name=pack_name,
                            title=pack_title,
                            stickers=[sticker]
                        )
                        await progress.edit_text(
                            escape_markdown_v2(
                                f"✅ New pack created with {sticker_format} sticker {emoji}\n"
                                f"📌 Reopen pack to see it"
                            ),
                            parse_mode="MarkdownV2",
                            reply_markup=reply_markup
                        )
                        break
                    except BadRequest as ce:
                        if "peer_id_invalid" in str(ce).lower():
                            await progress.edit_text(
                                escape_markdown_v2("❌ Please start the bot in PM with /start and try again"),
                                parse_mode="MarkdownV2"
                            )
                        else:
                            await progress.edit_text(
                                escape_markdown_v2(f"❌ Failed to create pack: {str(ce)}"),
                                parse_mode="MarkdownV2"
                            )
                        break
                elif "stickers_too_much" in err or "set_full" in err:
                    pack_count += 1
                    pack_name, pack_title = await create_pack_name(user, bot_username, sticker_format, pack_count)
                    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("View Pack", url=f"https://t.me/addstickers/{pack_name}")]])
                    continue
                elif "invalid sticker emoji" in err:
                    await progress.edit_text(
                        escape_markdown_v2(f"❌ Invalid emoji: {emoji}. Try 😄"),
                        parse_mode="MarkdownV2"
                    )
                    break
                elif "sticker_invalid" in err:
                    await progress.edit_text(
                        escape_markdown_v2("❌ Invalid sticker format. Use PNG/JPG/TGS/WEBM"),
                        parse_mode="MarkdownV2"
                    )
                    break
                else:
                    await progress.edit_text(
                        escape_markdown_v2(f"❌ Failed to add sticker: {str(e)}"),
                        parse_mode="MarkdownV2"
                    )
                    break
            except TelegramError as e:
                await progress.edit_text(
                    escape_markdown_v2(f"❌ Telegram error: {str(e)}. Try later"),
                    parse_mode="MarkdownV2"
                )
                break
    except ValueError as ve:
        await progress.edit_text(
            escape_markdown_v2(f"❌ {str(ve)}"),
            parse_mode="MarkdownV2"
        )

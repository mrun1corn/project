import os
from tempfile import NamedTemporaryFile
from telegram import Update, InputSticker, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest
from PIL import Image

def escape_markdown_v2(text: str) -> str:
    """Escape reserved characters for Telegram MarkdownV2."""
    reserved_chars = r'_[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in reserved_chars else char for char in text)

async def kang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    bot = context.bot
    msg = update.effective_message

    if not msg.reply_to_message:
        return await msg.reply_text(
            escape_markdown_v2("❌ Reply to an image or sticker with /kang"),
            parse_mode="MarkdownV2"
        )

    reply = msg.reply_to_message
    file_id = None

    # Check for valid input
    if reply.sticker:
        if reply.sticker.is_animated or reply.sticker.is_video:
            return await msg.reply_text(
                escape_markdown_v2("🚫 Animated/video stickers not supported"),
                parse_mode="MarkdownV2"
            )
        file_id = reply.sticker.file_id
    elif reply.photo:
        file_id = reply.photo[-1].file_id
    elif reply.document and (reply.document.mime_type or "").startswith("image/"):
        file_id = reply.document.file_id
    else:
        return await msg.reply_text(
            escape_markdown_v2("❌ Reply to an image or static sticker"),
            parse_mode="MarkdownV2"
        )

    # Get emoji: prefer context.args, then replied sticker's emoji, then default to 😄
    emoji = (
        "".join(context.args)
        if context.args
        else (reply.sticker.emoji if reply.sticker and reply.sticker.emoji else "😄")
    )

    progress = await msg.reply_text(
        escape_markdown_v2("⏳ Creating sticker..."),
        parse_mode="MarkdownV2"
    )

    # Download and process image
    try:
        tg_file = await bot.get_file(file_id)
        if tg_file.file_size > 5 * 1024 * 1024:  # 5MB limit
            return await msg.reply_text(
                escape_markdown_v2("❌ File too large. Max 5MB"),
                parse_mode="MarkdownV2"
            )

        with NamedTemporaryFile(suffix=".img", delete=False) as tmp:
            temp_name = tmp.name
            await tg_file.download_to_drive(temp_name)

        try:
            # Process image
            im = Image.open(temp_name).convert("RGBA")
            max_size = 512
            # Ensure one side is exactly 512 pixels
            if max(im.width, im.height) != max_size:
                scale = max_size / max(im.width, im.height)
                new_size = (int(im.width * scale), int(im.height * scale))
                im = im.resize(new_size, Image.Resampling.LANCZOS)
            if im.width > im.height:
                im = im.resize((max_size, int(max_size * im.height / im.width)), Image.Resampling.LANCZOS)
            else:
                im = im.resize((int(max_size * im.width / im.height), max_size), Image.Resampling.LANCZOS)

            with NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                png_name = tmp.name
                im.save(png_name, format="PNG")
                file_size = os.path.getsize(png_name)

                # Verify file size after processing
                if file_size > 512 * 1024:  # Telegram sticker size limit
                    await progress.edit_text(
                        escape_markdown_v2("❌ Sticker too large. Max 512KB"),
                        parse_mode="MarkdownV2"
                    )
                    return

                with open(png_name, "rb") as f:
                    sticker_data = f.read()

        finally:
            # Clean up temporary files
            for file_path in [temp_name, png_name]:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)

        # Prepare sticker pack
        bot_username = bot.username.lstrip('@').lower()
        base_name = user.username.lower() if user.username and user.username[0].isalpha() else f"u{user.id}"
        pack_count = 1
        base_pack_name = f"{base_name}_by_{bot_username}"
        pack_name = base_pack_name
        pack_title = f"{user.first_name or 'User'}'s Stickers"

        # Create inline button for sticker pack
        keyboard = [
            [InlineKeyboardButton("View Pack", url=f"https://t.me/addstickers/{pack_name}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        sticker = InputSticker(sticker=sticker_data, emoji_list=[emoji], format="static")

        # Try adding to existing pack or create new
        while True:
            try:
                await bot.add_sticker_to_set(user_id=user.id, name=pack_name, sticker=sticker)
                await progress.edit_text(
                    escape_markdown_v2(
                        f"✅ Added sticker with emoji {emoji}\n"
                        f"📌 Reopen pack to see it"
                    ),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
                break
            except BadRequest as e:
                err = str(e).lower()
                if "stickerset_invalid" in err or "not found" in err:
                    # Create new sticker set
                    try:
                        await bot.create_new_sticker_set(
                            user_id=user.id,
                            name=pack_name,
                            title=pack_title,
                            stickers=[sticker]
                        )
                        await progress.edit_text(
                            escape_markdown_v2(
                                f"✅ New pack created with emoji {emoji}\n"
                                f"📌 Reopen pack to see it"
                            ),
                            parse_mode="MarkdownV2",
                            reply_markup=reply_markup
                        )
                        break
                    except BadRequest as ce:
                        if "peer_id_invalid" in str(ce).lower():
                            await progress.edit_text(
                                escape_markdown_v2(
                                    f"❌ Please start the bot in pm with /start and try again"
                                ),
                                parse_mode="MarkdownV2"
                            )
                            break
                        else:
                            await progress.edit_text(
                                escape_markdown_v2(
                                    f"❌ Failed to create pack: {str(ce)}. Contact support"
                                ),
                                parse_mode="MarkdownV2"
                            )
                            break
                elif "stickers_too_much" in err or "set_full" in err:
                    # Try next pack with incremented name
                    pack_count += 1
                    pack_name = f"{base_pack_name}_{pack_count}"
                    pack_title = f"{user.first_name or 'User'}'s Stickers {pack_count}"
                    keyboard = [
                        [InlineKeyboardButton("View Pack", url=f"https://t.me/addstickers/{pack_name}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    continue
                elif "invalid sticker emoji" in err:
                    await progress.edit_text(
                        escape_markdown_v2(
                            f"❌ Invalid emoji: {emoji}. Try 😄"
                        ),
                        parse_mode="MarkdownV2"
                    )
                    break
                elif "sticker_invalid" in err:
                    await progress.edit_text(
                        escape_markdown_v2(
                            f"❌ Invalid image. Use PNG/JPEG"
                        ),
                        parse_mode="MarkdownV2"
                    )
                    break
                else:
                    await progress.edit_text(
                        escape_markdown_v2(
                            f"❌ Failed to add sticker: {str(e)}. Try again"
                        ),
                        parse_mode="MarkdownV2"
                    )
                    break
            except TelegramError as e:
                await progress.edit_text(
                    escape_markdown_v2(
                        f"❌ Telegram error: {str(e)}. Try later"
                    ),
                    parse_mode="MarkdownV2"
                )
                break
            except Exception as e:
                await progress.edit_text(
                    escape_markdown_v2(
                        f"❌ Error: {str(e)}. Contact support"
                    ),
                    parse_mode="MarkdownV2"
                )
                break

    except Exception as e:
        await progress.edit_text(
            escape_markdown_v2(
                f"❌ Error processing image: {str(e)}. Try another image"
            ),
            parse_mode="MarkdownV2"
        )
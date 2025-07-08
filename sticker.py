import os
from tempfile import NamedTemporaryFile
from telegram import Update, InputSticker
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest
from PIL import Image

async def kang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    bot = context.bot
    msg = update.effective_message

    if not msg.reply_to_message:
        return await msg.reply_text("❌ Please reply to a sticker or image using /kang.")

    reply = msg.reply_to_message
    file_id = None

    if reply.sticker:
        if reply.sticker.is_animated or reply.sticker.is_video:
            return await msg.reply_text("🚫 Animated or video stickers are not supported.")
        file_id = reply.sticker.file_id
    elif reply.photo:
        file_id = reply.photo[-1].file_id
    elif reply.document and (reply.document.mime_type or "").startswith("image/"):
        file_id = reply.document.file_id
    else:
        return await msg.reply_text("❌ Unsupported media type. Reply to an image or sticker.")

    emoji = (
        "".join(context.args)
        if context.args
        else (reply.sticker.emoji if reply.sticker and reply.sticker.emoji else "😄")
    )

    progress = await msg.reply_text("🔄 Processing...")

    temp_name = None
    png_name = None
    try:
        # Download the replied file
        tg_file = await bot.get_file(file_id)
        with NamedTemporaryFile(suffix=".img", delete=False) as tmp:
            temp_name = tmp.name
        await tg_file.download_to_drive(temp_name)

        # Open and convert to RGBA
        im = Image.open(temp_name).convert("RGBA")
        max_size = 512
        if im.width < max_size and im.height < max_size:
            scale = max_size / max(im.width, im.height)
            new_size = (int(im.width * scale), int(im.height * scale))
            im = im.resize(new_size, Image.Resampling.LANCZOS)
        else:
            im.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        # Save as PNG
        with NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            png_name = tmp.name
            im.save(png_name, format="PNG")

    except Exception as e:
        await progress.edit_text(f"❌ Error processing image: {e}")
        if temp_name and os.path.exists(temp_name):
            os.remove(temp_name)
        return
    finally:
        if temp_name and os.path.exists(temp_name):
            os.remove(temp_name)

    # Prepare sticker pack name and title
    bot_username = bot.username
    base_name = (
        user.username.lower()
        if user.username and user.username[0].isalpha()
        else f"u{user.id}"
    )
    pack_name = f"{base_name}_by_{bot_username}".lower()
    pack_title = f"{user.first_name or 'User'}'s Stickers"

    try:
        # Load PNG data as bytes
        with open(png_name, "rb") as f:
            sticker_data = f.read()

        sticker = InputSticker(
            sticker=sticker_data,
            emoji_list=[emoji],
            format="static"
        )

        # Try adding to existing sticker set
        await bot.add_sticker_to_set(
            user_id=user.id,
            name=pack_name,
            sticker=sticker
        )

        await progress.edit_text(
            f"✅ Sticker added!\n👉 [View Pack](https://t.me/addstickers/{pack_name})",
            parse_mode="Markdown"
        )

    except BadRequest as e:
        err = str(e).lower()
        if "stickerset_invalid" in err or "not found" in err or "invalid" in err:
            # Create new sticker set if not found
            try:
                await bot.create_new_sticker_set(
                    user_id=user.id,
                    name=pack_name,
                    title=pack_title,
                    stickers=[sticker]
                )
                await progress.edit_text(
                    f"🎉 New pack created!\n👉 [View Pack](https://t.me/addstickers/{pack_name})",
                    parse_mode="Markdown"
                )
            except TelegramError as ce:
                await progress.edit_text(f"❌ Failed to create sticker pack: {ce}")
        elif "stickers_too_much" in err or "set_full" in err:
            await progress.edit_text("❌ Sticker pack is full. Please create a new one.")
        elif "invalid sticker emoji" in err:
            await progress.edit_text("❌ Invalid emoji.")
        else:
            await progress.edit_text(f"❌ Failed to add sticker: {e}")

    except TelegramError as e:
        await progress.edit_text(f"❌ Telegram error: {e}")
    except Exception as e:
        await progress.edit_text(f"❌ Unexpected error: {e}")
    finally:
        if png_name and os.path.exists(png_name):
            os.remove(png_name)

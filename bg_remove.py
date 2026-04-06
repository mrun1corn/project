import os
import uuid
import html

import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

from command_template import CommandSpec, guard_command
from settings import settings


async def remove_bg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    output_file = None
    photo_path = None
    progress_message = None

    if not await guard_command(
        update,
        CommandSpec(name="bgremove", disabled_message="Background removal is currently disabled."),
    ):
        return

    if not settings.remove_bg_api_key:
        await update.message.reply_text(
            "<b>Remove Background Unavailable</b>\n<code>REMOVE_BG_API_KEY</code> is not configured yet.",
            parse_mode="HTML",
        )
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text(
            "<b>How To Use</b>\nReply to an image with <code>/bgremove</code> and I'll cut the background for you.",
            parse_mode="HTML",
        )
        return

    photo_file = await update.message.reply_to_message.photo[-1].get_file()
    os.makedirs("downloads", exist_ok=True)
    token = uuid.uuid4().hex
    photo_path = os.path.join("downloads", f"{photo_file.file_id}_{token}.jpg")
    await photo_file.download_to_drive(photo_path)

    try:
        progress_message = await update.message.reply_text(
            "<b>Background Removal Started</b>\n🪄 Please wait while I process the image.",
            parse_mode="HTML",
        )
        with open(photo_path, "rb") as image_file:
            form = aiohttp.FormData()
            form.add_field("size", "auto")
            form.add_field(
                "image_file",
                image_file,
                filename=os.path.basename(photo_path),
                content_type="image/jpeg",
            )

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.remove.bg/v1.0/removebg",
                    data=form,
                    headers={"X-Api-Key": settings.remove_bg_api_key},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    response_body = await response.read()

                    if response.status == 200:
                        output_file = os.path.join("downloads", f"{photo_file.file_id}_{token}_removed_bg.png")
                        with open(output_file, "wb") as out_file:
                            out_file.write(response_body)

                        with open(output_file, "rb") as processed_image:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=processed_image,
                                caption="<b>Background Removed</b>\n✨ Your image is ready.",
                                parse_mode="HTML",
                            )
                        if progress_message:
                            await progress_message.delete()
                    else:
                        try:
                            error_payload = await response.json()
                            error_message = error_payload.get("errors", [{}])[0].get("title", "An error occurred.")
                        except Exception:
                            error_message = response_body.decode("utf-8", errors="replace") or "An error occurred."
                        error_text = f"<b>Background Removal Failed</b>\n<code>{html.escape(error_message)}</code>"
                        if progress_message:
                            await progress_message.edit_text(error_text, parse_mode="HTML")
                        else:
                            await update.message.reply_text(error_text, parse_mode="HTML")
    except aiohttp.ClientError as exc:
        error_text = f"<b>Request Failed</b>\n🌐 I couldn't reach the background removal service.\n<code>{html.escape(str(exc))}</code>"
        if progress_message:
            await progress_message.edit_text(error_text, parse_mode="HTML")
        else:
            await update.message.reply_text(error_text, parse_mode="HTML")
    except Exception as exc:
        error_text = f"<b>Processing Failed</b>\n⚠️ Something went wrong while preparing the image.\n<code>{html.escape(str(exc))}</code>"
        if progress_message:
            await progress_message.edit_text(error_text, parse_mode="HTML")
        else:
            await update.message.reply_text(error_text, parse_mode="HTML")
    finally:
        try:
            if photo_path and os.path.exists(photo_path):
                os.remove(photo_path)
            if output_file and os.path.exists(output_file):
                os.remove(output_file)
        except OSError as cleanup_error:
            print(f"Cleanup error: {cleanup_error}")

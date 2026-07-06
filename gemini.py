import asyncio
import base64
import html
import json
import os
import re
import time
from io import BytesIO

import aiohttp
from telegram import InputMediaPhoto, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from command_template import CommandSpec, guard_command
from database import get_collection
from settings import settings


TEXT_MODEL = "gemini-2.5-flash"
IMAGE_MODEL = "gemini-2.5-flash-image"
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024
PROGRESS_UPDATE_INTERVAL = 1.5
MAX_HISTORY_TURNS = 10
TERMBIN_HOST = "termbin.com"
TERMBIN_PORT = 9999
USER_CONTEXTS_COLLECTION = get_collection("user_contexts")
IMAGE_REQUEST_PATTERN = re.compile(
    r"\b(generate|create|draw|make|design|render|illustrate|edit|change|turn).*\b(image|photo|picture|poster|logo|banner|wallpaper|icon|art)\b",
    re.IGNORECASE,
)


def sanitize_response(text: str) -> str:
    return re.sub(r'\n\s*\n+', '\n\n', text.strip())


def build_api_url(model_name: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.gemini_api_key}"


def wants_image_output(prompt_text: str, has_image_input: bool) -> bool:
    if not prompt_text:
        return has_image_input
    if IMAGE_REQUEST_PATTERN.search(prompt_text):
        return True
    return has_image_input and any(
        keyword in prompt_text.lower()
        for keyword in ("edit", "change", "turn", "replace", "remove", "make", "generate")
    )


def infer_extension(mime_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }.get(mime_type, ".bin")


async def load_user_context(user_id: int) -> dict:
    doc = await USER_CONTEXTS_COLLECTION.find_one({"_id": str(user_id)})
    if not doc:
        return {"history": [], "memory": {}}
    return {
        "history": doc.get("history", []),
        "memory": doc.get("memory", {}),
    }


async def save_user_context(user_id: int, user_data: dict) -> None:
    await USER_CONTEXTS_COLLECTION.update_one(
        {"_id": str(user_id)},
        {"$set": {"history": user_data.get("history", []), "memory": user_data.get("memory", {})}},
        upsert=True,
    )


async def upload_to_termbin(text: str) -> str:
    try:
        reader, writer = await asyncio.open_connection(TERMBIN_HOST, TERMBIN_PORT)
        writer.write(text.encode("utf-8"))
        await writer.drain()
        writer.write_eof()
        response_data = await asyncio.wait_for(reader.read(1024), timeout=10)
        writer.close()
        await writer.wait_closed()
        url = response_data.decode("utf-8").strip()
        if url and (url.startswith("https://termbin.com/") or url.startswith("http://termbin.com/")):
            return url
        raise Exception(f"Invalid termbin response: '{url}'")
    except Exception as exc:
        try:
            return await upload_to_termbin_http(text)
        except Exception as fallback_error:
            raise Exception(f"Socket method failed: {exc}, HTTP method failed: {fallback_error}")


async def upload_to_termbin_http(text: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://{TERMBIN_HOST}",
                data=text.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                timeout=10,
            ) as response:
                if response.status == 200:
                    url = (await response.text()).strip()
                    if url and (url.startswith("https://termbin.com/") or url.startswith("http://termbin.com/")):
                        return url
                    raise Exception(f"Invalid HTTP response: '{url}'")
                raise Exception(f"HTTP request failed with status {response.status}")
    except Exception:
        return await upload_to_termbin_subprocess(text)


async def upload_to_termbin_subprocess(text: str) -> str:
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as tmp_file:
            tmp_file.write(text)
            tmp_file_path = tmp_file.name

        try:
            process = await asyncio.create_subprocess_exec(
                "nc",
                TERMBIN_HOST,
                str(TERMBIN_PORT),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(input=text.encode("utf-8")), timeout=15)
            if process.returncode == 0:
                url = stdout.decode("utf-8").strip()
                if url and (url.startswith("https://termbin.com/") or url.startswith("http://termbin.com/")):
                    return url
                raise Exception(f"Invalid subprocess response: '{url}'")
            raise Exception(f"nc command failed: {stderr.decode('utf-8')}")
        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
    except Exception as exc:
        raise Exception(f"Subprocess upload failed: {exc}")


async def get_gemini_response(
    conversation_history: list,
    *,
    file_data: str | None = None,
    file_mime_type: str | None = None,
    generate_image: bool = False,
) -> tuple[dict, float]:
    start = time.time()

    current_user_parts = []
    if conversation_history and conversation_history[-1].get("parts"):
        current_user_parts.extend(conversation_history[-1]["parts"])

    if file_data and file_mime_type:
        current_user_parts.append({"inlineData": {"mimeType": file_mime_type, "data": file_data}})

    model_name = IMAGE_MODEL if generate_image else TEXT_MODEL
    payload = {"contents": conversation_history[:-1] + [{"role": "user", "parts": current_user_parts}]}
    if generate_image:
        payload["generationConfig"] = {"responseModalities": ["TEXT", "IMAGE"]}

    headers = {"Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(build_api_url(model_name), json=payload, headers=headers, timeout=120) as resp:
                if resp.status != 200:
                    try:
                        error_details = await resp.text()
                    except Exception:
                        error_details = "Unknown error details"
                    return {"text": f"Gemini API error: {resp.status} - {error_details}", "images": []}, 0.0

                data = await resp.json()
                candidates = data.get("candidates")
                if not candidates or not isinstance(candidates, list) or not candidates[0].get("content"):
                    safety_ratings = data.get("promptFeedback", {}).get("safetyRatings")
                    if safety_ratings:
                        for rating in safety_ratings:
                            if rating.get("blockReason"):
                                return {
                                    "text": f"Gemini blocked the response for safety reasons: {rating.get('category')} - {rating.get('blockReason')}",
                                    "images": [],
                                }, 0.0
                    return {"text": f"Unexpected Gemini response format or no content: {json.dumps(data, indent=2)}", "images": []}, 0.0

                parts = candidates[0]["content"].get("parts", [])
                text_parts: list[str] = []
                image_parts: list[dict] = []
                for part in parts:
                    if part.get("text"):
                        text_parts.append(part["text"])
                    inline_data = part.get("inlineData") or part.get("inline_data")
                    if inline_data and inline_data.get("data") and inline_data.get("mimeType", "").startswith("image/"):
                        try:
                            image_parts.append(
                                {
                                    "mime_type": inline_data["mimeType"],
                                    "data": base64.b64decode(inline_data["data"]),
                                }
                            )
                        except Exception:
                            continue

                elapsed = time.time() - start
                return {"text": "\n\n".join(text_parts).strip(), "images": image_parts}, elapsed
        except aiohttp.client_exceptions.ClientConnectorError:
            return {"text": "Network error connecting to Gemini API. Please check your internet connection.", "images": []}, 0.0
        except asyncio.TimeoutError:
            return {"text": "Gemini API request timed out. Please try again.", "images": []}, 0.0
        except Exception as exc:
            return {"text": f"An unexpected error occurred while contacting Gemini: {exc}", "images": []}, 0.0


async def process_file(file_path: str, file_name: str) -> tuple[str, str]:
    try:
        with open(file_path, "rb") as file_handle:
            binary_data = file_handle.read()
            base64_data = base64.b64encode(binary_data).decode("utf-8")

        extension = os.path.splitext(file_name)[1].lower()
        mime_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain",
        }
        mime_type = mime_type_map.get(extension, "application/octet-stream")
        return base64_data, mime_type
    except Exception as exc:
        return f"Error processing file: {exc}", None


async def send_generated_images(context: ContextTypes.DEFAULT_TYPE, chat_id: int, images: list[dict], caption_html: str | None) -> None:
    if not images:
        return

    if len(images) == 1:
        image = images[0]
        image_file = BytesIO(image["data"])
        image_file.name = f"gemini_image{infer_extension(image['mime_type'])}"
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=image_file,
            caption=caption_html[:MAX_CAPTION_LENGTH] if caption_html else None,
            parse_mode="HTML" if caption_html else None,
        )
        return

    media_group = []
    for index, image in enumerate(images[:10]):
        image_file = BytesIO(image["data"])
        image_file.name = f"gemini_image_{index + 1}{infer_extension(image['mime_type'])}"
        media_group.append(
            InputMediaPhoto(
                media=image_file,
                caption=caption_html[:MAX_CAPTION_LENGTH] if index == 0 and caption_html else None,
                parse_mode="HTML" if index == 0 and caption_html else None,
            )
        )
    await context.bot.send_media_group(chat_id=chat_id, media=media_group)


async def _extract_attachment(replied_message, context, prompt_text: str) -> tuple[str | None, str | None, str]:
    """
    Processes the attachment in the replied message if present.
    Returns a tuple of (file_data, mime_type, updated_prompt_text).
    """
    file_data = None
    mime_type = None
    file = None
    file_name = None
    temp_file_path = None

    if replied_message.document:
        file = replied_message.document
        file_name = file.file_name
    elif replied_message.photo:
        file = replied_message.photo[-1]
        file_name = "temp_image.jpg"

    if file:
        try:
            file_obj = await context.bot.get_file(file.file_id)
            temp_file_path = f"temp_{file.file_unique_id}_{file_name}"
            await file_obj.download_to_drive(temp_file_path)

            file_data, mime_type = await process_file(temp_file_path, file_name)
            if "Error" in file_data:
                raise ValueError(file_data)
            if not prompt_text:
                prompt_text = "Describe the content of this file."
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
    elif replied_message.text and not prompt_text:
        prompt_text = replied_message.text

    return file_data, mime_type, prompt_text


def _start_progress_tracker(progress_msg, generate_image: bool, start_time: float) -> asyncio.Task:
    dots = ["", ".", "..", "..."]

    async def update_progress():
        dot_index = 0
        while True:
            elapsed = time.time() - start_time
            try:
                status_line = "🖼️ Generating image" if generate_image else "🤖 Thinking"
                await progress_msg.edit_text(
                    f"<b>AI Assistant</b>\n{status_line}{dots[dot_index]}\n⏱️ {elapsed:.1f}s",
                    parse_mode="HTML",
                )
            except BadRequest:
                break
            dot_index = (dot_index + 1) % len(dots)
            await asyncio.sleep(PROGRESS_UPDATE_INTERVAL)

    return asyncio.create_task(update_progress())


async def _render_ai_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    response: dict,
    elapsed: float,
    progress_msg,
    conversation_history: list,
    user_id: int,
    user_data: dict,
) -> None:
    response_text = response.get("text", "")
    generated_images = response.get("images", [])
    timing_info = f"\n\n<i>Generated in {elapsed:.1f}s</i>"

    if generated_images:
        caption_html = None
        if response_text:
            caption_html = sanitize_response(html.escape(response_text)) + timing_info

        await progress_msg.edit_text(
            "<b>AI Assistant</b>\n🖼️ Uploading the generated image...",
            parse_mode="HTML",
        )
        await send_generated_images(context, update.effective_chat.id, generated_images, caption_html)

        if response_text and len(caption_html or "") > MAX_CAPTION_LENGTH:
            await progress_msg.edit_text(
                sanitize_response(html.escape(response_text))[: MAX_MESSAGE_LENGTH - 80] + timing_info,
                parse_mode="HTML",
            )
        else:
            await progress_msg.delete()
    else:
        escaped_html = html.escape(response_text)
        sanitized_reply = sanitize_response(escaped_html)
        full_message = f"{sanitized_reply}{timing_info}"

        if len(full_message) > MAX_MESSAGE_LENGTH:
            try:
                await progress_msg.edit_text(
                    f"<b>AI Assistant</b>\n📦 The reply is long ({len(response_text)} characters). Uploading the full result...",
                    parse_mode="HTML",
                )
                termbin_url = await upload_to_termbin(response_text)
                final_message = f"<b>Full Response Uploaded</b>\n🔗 {html.escape(termbin_url)}{timing_info}"
                await progress_msg.edit_text(final_message, parse_mode="HTML")
            except Exception as exc:
                truncated_reply = sanitized_reply[: MAX_MESSAGE_LENGTH - 220] + f"...\n\n<i>Response was truncated because upload failed: {html.escape(str(exc))}</i>"
                await progress_msg.edit_text(f"{truncated_reply}{timing_info}", parse_mode="HTML")
        else:
            await progress_msg.edit_text(full_message, parse_mode="HTML")

    history_parts = []
    if response_text:
        history_parts.append({"text": response_text})
    elif generated_images:
        history_parts.append({"text": "[Generated image response]"})
    if history_parts:
        conversation_history.append({"role": "model", "parts": history_parts})
        user_data["history"] = conversation_history
        await save_user_context(user_id, user_data)


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user_id = update.effective_user.id

    if not await guard_command(update, CommandSpec(name="ai", disabled_message="⚠️ AI is currently disabled.")):
        return

    user_data = await load_user_context(user_id)
    conversation_history = user_data["history"]
    replied_message = message.reply_to_message
    file_data = None
    mime_type = None
    prompt_text = " ".join(context.args) if context.args else ""

    if replied_message:
        try:
            file_data, mime_type, prompt_text = await _extract_attachment(replied_message, context, prompt_text)
        except ValueError as exc:
            await message.reply_text(
                f"<b>File Processing Failed</b>\n<code>{html.escape(str(exc))}</code>",
                parse_mode="HTML",
            )
            return
        except Exception as exc:
            await message.reply_text(
                f"<b>Attachment Processing Failed</b>\n<code>{html.escape(str(exc))}</code>",
                parse_mode="HTML",
            )
            return

    if not prompt_text and not (file_data and mime_type):
        await message.reply_text(
            "<b>How To Use AI</b>\nSend <code>/ai your question</code> or reply to a file or image with <code>/ai</code>.\nTo generate images, ask clearly for an image, poster, logo, illustration, or edit.",
            parse_mode="HTML",
        )
        return

    progress_msg = await message.reply_text("<b>AI Assistant</b>\n🤖 Thinking...", parse_mode="HTML")

    user_message_parts = []
    if prompt_text:
        user_message_parts.append({"text": prompt_text})
    if file_data and mime_type:
        user_message_parts.append({"inlineData": {"mimeType": mime_type, "data": file_data}})

    if not user_message_parts:
        await message.reply_text("⚠️ I couldn't find any valid input for Gemini.")
        return

    generate_image = wants_image_output(prompt_text, bool(file_data and mime_type and mime_type.startswith("image/")))
    conversation_history.append({"role": "user", "parts": user_message_parts})
    if len(conversation_history) > MAX_HISTORY_TURNS * 2:
        conversation_history = conversation_history[-(MAX_HISTORY_TURNS * 2):]

    start_time = time.time()
    progress_task = _start_progress_tracker(progress_msg, generate_image, start_time)

    try:
        response, elapsed = await get_gemini_response(
            conversation_history=conversation_history,
            file_data=file_data,
            file_mime_type=mime_type,
            generate_image=generate_image,
        )
        await _render_ai_response(
            update=update,
            context=context,
            response=response,
            elapsed=elapsed,
            progress_msg=progress_msg,
            conversation_history=conversation_history,
            user_id=user_id,
            user_data=user_data,
        )
    finally:
        progress_task.cancel()


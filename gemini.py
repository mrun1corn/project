import aiohttp
import asyncio
import json
import os
import re
import time
import base64
import html
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from aiocache import Cache, cached
from config import ADMIN_CHAT_ID
from comm_checker import check_user_approval, command_states

# Constants
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key=AIzaSyAVbzsMcfYambTXj7N7-SHwYyW0ErrCgTs"
CONTEXT_FILE = "user_context.json"
CONTEXT_HISTORY_LIMIT = 5
PROGRESS_UPDATE_INTERVAL = 1.5
MAX_MESSAGE_LENGTH = 4096  # Telegram's max message length

def sanitize_response(text: str) -> str:
    text = re.sub(r'\n\s*\n+', '\n\n', text.strip())
    return text

def extract_context_info(prompt: str, response: str) -> dict:
    prompt_lower = prompt.lower()
    info = {}
    if "friend" in prompt_lower and "name" in prompt_lower:
        match = re.search(r'\b[A-Z][a-z]+\b', response)
        if match:
            info["friend_name"] = match.group()
    return info

def load_context() -> dict:
    if os.path.exists(CONTEXT_FILE):
        try:
            with open(CONTEXT_FILE, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}

async def save_context_async(context: dict):
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: json.dump(context, open(CONTEXT_FILE, "w"), indent=2))
    except Exception:
        pass

def gemini_cache_key_builder(func, *args, **kwargs):
    user_id = kwargs.get("user_id", "anonymous")
    prompt = args[0] if args else "noprompt"
    return f"{user_id}:{prompt[:50]}"

@cached(ttl=3600, cache=Cache.MEMORY, key_builder=gemini_cache_key_builder)
async def get_gemini_response(prompt: str, file_data: str = None, file_mime_type: str = None, user_id: str = None) -> tuple[str, float]:
    start = time.time()
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    if file_data and file_mime_type:
        payload["contents"][0]["parts"].append({
            "inlineData": {"mimeType": file_mime_type, "data": file_data}
        })
    headers = {"Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(GEMINI_API_URL, json=payload, headers=headers, timeout=30) as resp:
                if resp.status != 200:
                    try:
                        error_details = await resp.text()
                    except:
                        error_details = "Unknown error"
                    return f"⚠️ Gemini API error: {resp.status} - {error_details}", 0.0
                data = await resp.json()
                candidates = data.get("candidates")
                if not candidates or "content" not in candidates[0]:
                    return f"⚠️ Unexpected Gemini response format: {json.dumps(data, indent=2)}", 0.0
                reply = candidates[0]["content"]["parts"][0]["text"]
                elapsed = time.time() - start
                return reply.strip(), elapsed
        except Exception as e:
            return f"⚠️ Gemini request error: {str(e)}", 0.0

async def build_prompt(user_id: str, prompt: str) -> tuple[str, dict, list, dict]:
    user_context = load_context()
    user_data = user_context.get(user_id, {"memory": {}, "history": []})
    memory = user_data["memory"]
    history = user_data["history"]
    prompt_lower = prompt.lower()
    full_prompt = f"Answer this: {prompt}"
    if "friend" in prompt_lower and "name" in prompt_lower and "friend_name" in memory:
        full_prompt = f"My friend's name is {memory['friend_name']}.\n{prompt}"
    elif any(k in prompt_lower for k in ["more", "continue", "next", "follow up"]):
        if history:
            full_prompt = f"Earlier we discussed: '{history[-1]}'\nNow: {prompt}"
    history.append(prompt)
    if len(history) > CONTEXT_HISTORY_LIMIT:
        history = history[-CONTEXT_HISTORY_LIMIT:]
    return full_prompt, memory, history, user_context

async def process_file(file_path: str, file_name: str) -> tuple[str, str]:
    try:
        with open(file_path, "rb") as f:
            binary_data = f.read()
            base64_data = base64.b64encode(binary_data).decode("utf-8")
        extension = os.path.splitext(file_name)[1].lower()
        mime_type = ("image/jpeg" if extension in [".jpg", ".jpeg"] else
                     "image/png" if extension == ".png" else
                     "application/pdf" if extension == ".pdf" else
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if extension == ".docx" else
                     "text/plain" if extension == ".txt" else
                     "application/octet-stream")
        return base64_data, mime_type
    except Exception as e:
        return f"Error processing file: {str(e)}", None

async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_CHAT_ID and not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("🔒 You're not approved to use this command.")
        return
    if not command_states.get('ai', True) and user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ AI command is currently disabled.")
        return
    replied_message = update.message.reply_to_message
    file_data = None
    mime_type = None
    prompt = " ".join(context.args) if context.args else ""
    if replied_message:
        if replied_message.document or replied_message.photo:
            if replied_message.document:
                file = replied_message.document
                file_name = file.file_name
                file_obj = await context.bot.get_file(file.file_id)
                file_path = f"temp_{file_name}"
                await file_obj.download_to_drive(file_path)
            elif replied_message.photo:
                photo = replied_message.photo[-1]
                file_obj = await context.bot.get_file(photo.file_id)
                file_path = "temp_image.jpg"
                file_name = "temp_image.jpg"
                await file_obj.download_to_drive(file_path)
            try:
                file_data, mime_type = await process_file(file_path, file_name)
                if "Error" in file_data:
                    await update.message.reply_text(file_data)
                    return
            finally:
                os.remove(file_path)
            if not prompt:
                prompt = "Describe the content of this file."
        if file_data and mime_type:
            progress_msg = await update.message.reply_text("🧠 Thinking...")
            full_prompt, memory, history, user_context = await build_prompt(user_id, prompt)
            dots = ["", ".", "..", "..."]
            dot_index = 0
            start_time = time.time()
            async def update_progress():
                nonlocal dot_index
                while True:
                    elapsed = time.time() - start_time
                    try:
                        await progress_msg.edit_text(f"Processing{dots[dot_index]} ({elapsed:.1f}s)")
                    except BadRequest:
                        pass
                    dot_index = (dot_index + 1) % len(dots)
                    await asyncio.sleep(PROGRESS_UPDATE_INTERVAL)
            progress_task = asyncio.create_task(update_progress())
            try:
                response_text, elapsed = await get_gemini_response(full_prompt, file_data, mime_type, user_id)
                escaped_html = html.escape(response_text)
                sanitized_reply = sanitize_response(escaped_html)
                if len(sanitized_reply) > MAX_MESSAGE_LENGTH:
                    sanitized_reply = sanitized_reply[:MAX_MESSAGE_LENGTH - 100] + "...\n\n⚠️ Response was truncated."
                await progress_msg.edit_text(f"{sanitized_reply}\n\n✨ Generated in {elapsed:.1f}s", parse_mode="HTML")
                new_info = extract_context_info(prompt, response_text)
                memory.update(new_info)
                user_context[user_id] = {"memory": memory, "history": history}
                asyncio.create_task(save_context_async(user_context))
            finally:
                progress_task.cancel()
    else:
        if not context.args:
            await update.message.reply_text("Try: `/ai what is Python?` or reply to a file or image with a query.")
            return
        progress_msg = await update.message.reply_text("🧠 Thinking...")
        full_prompt, memory, history, user_context = await build_prompt(user_id, prompt)
        dots = ["", ".", "..", "..."]
        dot_index = 0
        start_time = time.time()
        async def update_progress():
            nonlocal dot_index
            while True:
                elapsed = time.time() - start_time
                try:
                    await progress_msg.edit_text(f"Processing{dots[dot_index]} ({elapsed:.1f}s)")
                except BadRequest:
                    pass
                dot_index = (dot_index + 1) % len(dots)
                await asyncio.sleep(PROGRESS_UPDATE_INTERVAL)
        progress_task = asyncio.create_task(update_progress())
        try:
            response_text, elapsed = await get_gemini_response(full_prompt, user_id=user_id)
            escaped_html = html.escape(response_text)
            sanitized_reply = sanitize_response(escaped_html)
            if len(sanitized_reply) > MAX_MESSAGE_LENGTH:
                sanitized_reply = sanitized_reply[:MAX_MESSAGE_LENGTH - 100] + "...\n\n⚠️ Response was truncated."
            await progress_msg.edit_text(f"{sanitized_reply}\n\n✨ Generated in {elapsed:.1f}s", parse_mode="HTML")
            new_info = extract_context_info(prompt, response_text)
            memory.update(new_info)
            user_context[user_id] = {"memory": memory, "history": history}
            asyncio.create_task(save_context_async(user_context))
        finally:
            progress_task.cancel()

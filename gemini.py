import aiohttp
import asyncio
import json
import os
import re
import time
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from aiocache import Cache, cached
from config import ADMIN_CHAT_ID
from comm_checker import check_user_approval, command_states
from docx import Document
import fitz  # PyMuPDF for PDF handling
from PIL import Image
import pytesseract  # For OCR on images

# Constants
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=AIzaSyAVbzsMcfYambTXj7N7-SHwYyW0ErrCgTs"
CONTEXT_FILE = "user_context.json"
CONTEXT_HISTORY_LIMIT = 5
PROGRESS_UPDATE_INTERVAL = 1.5

def escape_markdown(text: str) -> str:
    """
    Escapes Telegram markdown special characters, preserving code blocks.
    """
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    if "```" in text:
        parts = re.split(r'(```.*?```)', text, flags=re.DOTALL)
        for i in range(len(parts)):
            if not parts[i].startswith("```"):
                parts[i] = re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', parts[i])
        return "".join(parts)
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def extract_context_info(prompt: str, response: str) -> dict:
    """Extract structured memory from user interaction."""
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

@cached(ttl=3600, cache=Cache.MEMORY, key_builder=lambda *args: f"{args[1]}:{args[0]}")
async def get_gemini_response(prompt: str, user_id: str) -> tuple[str, float]:
    start = time.time()
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    headers = {
        "Content-Type": "application/json",
    }

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
    """Create full prompt with context memory."""
    user_context = load_context()
    user_data = user_context.get(user_id, {"memory": {}, "history": []})
    memory = user_data["memory"]
    history = user_data["history"]

    prompt_lower = prompt.lower()
    full_prompt = f"Answer this: {prompt}"

    if "friend" in prompt_lower and "name" in prompt_lower and "friend_name" in memory:
        full_prompt = f"My friend's name is {memory['friend_name']}.\n\n{prompt}"
    elif any(k in prompt_lower for k in ["more", "continue", "next", "follow up"]):
        if history:
            full_prompt = f"Earlier we discussed: '{history[-1]}'\nNow: {prompt}"

    history.append(prompt)
    if len(history) > CONTEXT_HISTORY_LIMIT:
        history = history[-CONTEXT_HISTORY_LIMIT:]

    return full_prompt, memory, history, user_context

async def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF file using PyMuPDF."""
    try:
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"

async def extract_text_from_docx(file_path: str) -> str:
    """Extract text from a Word document."""
    try:
        doc = Document(file_path)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        return f"Error extracting text from Word document: {str(e)}"

async def extract_text_from_image(file_path: str) -> str:
    """Extract text from an image using OCR."""
    try:
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)
        return text
    except Exception as e:
        return f"Error extracting text from image: {str(e)}"

async def process_file(file_path: str, file_name: str) -> str:
    """Process the file based on its extension and return its content."""
    extension = os.path.splitext(file_name)[1].lower()
    
    if extension == ".pdf":
        return await extract_text_from_pdf(file_path)
    elif extension in [".docx", ".doc"]:
        return await extract_text_from_docx(file_path)
    elif extension == ".txt":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading text file: {str(e)}"
    elif extension in [".png", ".jpg", ".jpeg", ".tiff"]:
        return await extract_text_from_image(file_path)
    else:
        return f"Unsupported file type: {extension}"

# ✅ MAIN COMMAND HANDLER
async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)

    if user_id != ADMIN_CHAT_ID and not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("🔒 You're not approved to use this command.")
        return

    if not command_states.get('ai', True) and user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ AI command is currently disabled.")
        return

    # Check if the message is a reply to another message
    replied_message = update.message.reply_to_message
    file_content = None
    prompt = " ".join(context.args) if context.args else ""

    if replied_message:
        # Check if the replied message contains a document
        if replied_message.document:
            file = replied_message.document
            file_name = file.file_name
            # Download the file
            file_obj = await context.bot.get_file(file.file_id)
            file_path = f"temp_{file_name}"
            await file_obj.download_to_drive(file_path)

            # Process the file based on its type
            try:
                file_content = await process_file(file_path, file_name)
            finally:
                os.remove(file_path)  # Clean up the temporary file

            if "Error" in file_content:
                await update.message.reply_text(file_content)
                return

        # Check if the replied message contains a photo
        elif replied_message.photo:
            # Get the highest resolution photo
            photo = replied_message.photo[-1]  # Last item is the highest quality
            file_obj = await context.bot.get_file(photo.file_id)
            file_path = "temp_image.jpg"
            await file_obj.download_to_drive(file_path)

            # Extract text from the image
            try:
                file_content = await extract_text_from_image(file_path)
            finally:
                os.remove(file_path)  # Clean up the temporary file

            if "Error" in file_content:
                await update.message.reply_text(file_content)
                return

        if file_content:
            # If there's no prompt, ask the AI to describe the file content
            if not prompt:
                prompt = f"Describe the content of this file:\n\n{file_content}"
            else:
                prompt = f"File content:\n{file_content}\n\nUser query: {prompt}"
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
        response_text, elapsed = await get_gemini_response(full_prompt, user_id)
        reply = re.sub(r'[^\x00-\x7F]+', '', response_text)
        safe_reply = escape_markdown(reply)
        await progress_msg.edit_text(f"{safe_reply}\n\n✨ Generated in {elapsed:.1f}s", parse_mode="Markdown")

        new_info = extract_context_info(prompt, reply)
        memory.update(new_info)
        user_context[user_id] = {"memory": memory, "history": history}
        asyncio.create_task(save_context_async(user_context))

    finally:
        progress_task.cancel()
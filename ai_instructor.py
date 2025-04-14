import aiohttp
import asyncio
import json
import os
import re
import time
from telegram import Update
from telegram.ext import ContextTypes
from comm_checker import command_states, check_user_approval
from telegram.error import BadRequest
from config import ADMIN_CHAT_ID

# Ollama configuration
OLLAMA_URL = "http://localhost:11434/api/generate"
RETRY_LIMIT = 2
TIMEOUT = 120

# JSON file for user context
CONTEXT_FILE = "user_context.json"

def load_context():
    try:
        if os.path.exists(CONTEXT_FILE):
            if os.path.getsize(CONTEXT_FILE) == 0:
                print("Context file is empty, initializing with empty dict")
                return {}
            with open(CONTEXT_FILE, "r") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    print(f"Invalid context format: {data}, resetting to empty dict")
                    return {}
                return data
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing context JSON: {e}, resetting to empty dict")
        return {}
    except Exception as e:
        print(f"Error loading context: {e}, resetting to empty dict")
        return {}

def save_context(context):
    try:
        if not isinstance(context, dict):
            print("Context is not a dict, skipping save")
            return
        with open(CONTEXT_FILE, "w") as f:
            json.dump(context, f, indent=2)
    except Exception as e:
        print(f"Error saving context: {e}")

def choose_model(prompt: str) -> str:
    prompt = prompt.lower()
    if any(word in prompt for word in ["code", "function", "class", "def", "script", "python"]):
        return "codellama"
    elif any(word in prompt for word in ["complex", "detailed", "explain in depth"]):
        return "mistral"
    return "dolphin-mistral"

async def stream_response(url, payload, progress_msg, user_id, fallback_model=False):
    reply = ""
    last_text = ""
    dots = ["", ".", "..", "..."]
    dot_index = 0

    prompt_lower = payload["prompt"].lower()
    lang = "python"  # Default
    language_map = {
        "python": ["python", "py"],
        "javascript": ["javascript", "js"],
        "java": ["java"],
        "c": ["c language", "in c "],
        "cpp": ["c++", "cpp"],
        "php": ["php"],
        "rust": ["rust"],
        "go": ["go", "golang"],
        "zig": ["zig"],
        "html": ["html"],
        "css": ["css"],
    }
    for detected_lang, keywords in language_map.items():
        if any(keyword in prompt_lower for keyword in keywords):
            lang = detected_lang
            break

    is_code = any(keyword in prompt_lower for keyword in ["code", "python", "java", "js", "php"])
    start_time = time.time()
    elapsed = 0

    async def update_progress():
        nonlocal dot_index, elapsed
        while True:
            elapsed = time.time() - start_time
            dot_index = (dot_index + 1) % len(dots)
            formatted_text = f"Thinking... {elapsed:.1f}s{dots[dot_index]}"
            try:
                await progress_msg.edit_text(formatted_text + "\n" + reply, parse_mode="Markdown")
            except BadRequest:
                pass
            await asyncio.sleep(0.4)

    async with aiohttp.ClientSession() as session:
        progress_task = asyncio.create_task(update_progress())

        for attempt in range(RETRY_LIMIT):
            try:
                async with session.post(url, json=payload, timeout=TIMEOUT) as response:
                    if response.status != 200:
                        progress_task.cancel()
                        await progress_msg.edit_text("Yikes, AI’s tripping!")
                        return

                    async for line in response.content:
                        if line:
                            try:
                                chunk = json.loads(line.decode("utf-8").replace("data: ", ""))
                                token = chunk.get("response", "")
                                if token:
                                    reply += token
                                    if len(reply) >= len(last_text) + 50:
                                        last_text = reply[:4096]
                                        formatted_text = last_text
                                        if is_code:
                                            formatted_text = re.sub(r'`', r'\`', last_text)
                                            formatted_text = f"```{lang}\n{formatted_text}\n```"
                                        try:
                                            await progress_msg.edit_text(f"Thinking... {elapsed:.1f}s{dots[dot_index]}\n{formatted_text}", parse_mode="Markdown")
                                        except BadRequest:
                                            await progress_msg.edit_text(last_text)
                                        dot_index = 0
                            except json.JSONDecodeError:
                                continue

                    progress_task.cancel()

                    final_text = reply[:4096] if reply.strip() else "Nada to say! Try again?"
                    elapsed = time.time() - start_time
                    if is_code:
                        final_text = re.sub(r'`', r'\`', final_text)
                        final_text = f"```{lang}\n{final_text}\n```"
                    final_text = f"{final_text}\n✨ Generated in {elapsed:.1f}s"

                    try:
                        if final_text != last_text:
                            await progress_msg.edit_text(f"Thinking... {elapsed:.1f}s{dots[dot_index]}\n{final_text}", parse_mode="Markdown")
                    except BadRequest:
                        await progress_msg.edit_text(reply[:4096])
                    return

            except aiohttp.ClientConnectionError:
                if attempt < RETRY_LIMIT - 1:
                    await asyncio.sleep(1)
                    continue
                error_msg = "AI’s napping—can’t reach it! 😴"
            except aiohttp.ClientResponseError as e:
                error_msg = f"Server error: {e.status}. Try later!"
            except asyncio.TimeoutError:
                error_msg = "Taking too long! Let’s retry."

            progress_task.cancel()
            if fallback_model and payload["model"] != "tinyllama":
                await progress_msg.edit_text("Switching to tinyllama for speed...")
                payload["model"] = "tinyllama"
                continue
            else:
                await progress_msg.edit_text(error_msg)
                return

async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)

    if user_id != ADMIN_CHAT_ID:
        if not await check_user_approval(update.effective_user.id):
            await update.message.reply_text("🔒 You are not approved to use this command.")
            return

    if not command_states.get('ai', True) and user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ AI command is disabled.")
        return

    if not context.args:
        await update.message.reply_text("Hey! Try: /ai what’s up?")
        return

    prompt = " ".join(context.args)
    model = choose_model(prompt)
    progress_msg = await update.message.reply_text(f"Chatting with {model}... 😎")

    user_context = load_context()
    user_data = user_context.get(user_id, {"history": [], "last_model": ""})

    print(f"user_data for {user_id}: {user_data}")

    if not isinstance(user_data, dict):
        print(f"Error: user_data is not a dictionary for {user_id}, resetting.")
        user_data = {"history": [], "last_model": ""}

    history = user_data["history"]
    last_model = user_data["last_model"]

    full_prompt = prompt
    if history and (model == last_model or not last_model):
        context_lines = [f"Previous: {p}" for p in history[-3:]]
        full_prompt = "\n".join(context_lines + [f"Now: {prompt}"])

    history.append(prompt)
    if len(history) > 5:
        history = history[-5:]
    user_context[user_id] = {"history": history, "last_model": model}
    save_context(user_context)

    payload = {"model": model, "prompt": full_prompt, "stream": True}
    asyncio.create_task(stream_response(OLLAMA_URL, payload, progress_msg, user_id, fallback_model=True))
import asyncio
import json
import os
import time
import re
from telegram import Update
from telegram.ext import ContextTypes
from comm_checker import command_states, check_user_approval
from telegram.error import BadRequest
from config import ADMIN_CHAT_ID, OLLAMA_URL
from ollama import choose_model, stream_response
from functools import lru_cache

# Constants
CONTEXT_FILE = "user_context.json"
CONTEXT_HISTORY_LIMIT = 5
PROGRESS_UPDATE_INTERVAL = 1.5

@lru_cache(maxsize=128)
def load_context_cached():
    try:
        if os.path.exists(CONTEXT_FILE) and os.path.getsize(CONTEXT_FILE) > 0:
            with open(CONTEXT_FILE, "r") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {}
                return data
        return {}
    except json.JSONDecodeError:
        return {}
    except Exception:
        return {}

async def save_context_async(context):
    try:
        if not isinstance(context, dict):
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: json.dump(context, open(CONTEXT_FILE, "w"), indent=2))
    except Exception:
        pass

def extract_context_info(prompt: str, response: str) -> dict:
    """Extract key information from prompt and response for memory."""
    prompt_lower = prompt.lower()
    info = {}
    if "friend" in prompt_lower and "name" in prompt_lower:
        # Look for names in prompt or response
        name_match = re.search(r'\b\w+\b', response, re.IGNORECASE)
        if name_match and name_match.group() not in ["is", "the", "a", "my"]:
            info["friend_name"] = name_match.group()
        elif "is" in prompt_lower:
            name_match = re.search(r'is\s+(\w+)', prompt_lower)
            if name_match:
                info["friend_name"] = name_match.group(1).capitalize()
    return info

async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)

    if user_id != ADMIN_CHAT_ID and not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("🔒 You are not approved to use this command.")
        return

    if not command_states.get('ai', True) and user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ AI command is disabled.")
        return

    if not context.args:
        await update.message.reply_text("Hey! Try: /ai what’s up?")
        return

    prompt = " ".join(context.args)
    print(f"Query: {prompt}")
    model = choose_model(prompt)
    progress_msg = await update.message.reply_text(f"Chatting with {model}... 😎")

    user_context = load_context_cached()
    user_data = user_context.get(user_id, {"memory": {}, "history": []})

    if not isinstance(user_data, dict):
        user_data = {"memory": {}, "history": []}

    memory = user_data["memory"]
    history = user_data["history"]

    # Build prompt with relevant memory
    full_prompt = f"Answer this query directly: {prompt}"
    prompt_lower = prompt.lower()
    if "friend" in prompt_lower and "name" in prompt_lower and "friend_name" in memory:
        full_prompt = f"Use this info: friend's name is {memory['friend_name']}.\nAnswer: {prompt}"
    elif any(word in prompt_lower for word in ["more", "follow up", "continue", "tell me more", "go on", "next"]):
        if history:
            full_prompt = f"Based on prior query: {history[-1]}\nAnswer: {prompt}"

    history.append(prompt)
    if len(history) > CONTEXT_HISTORY_LIMIT:
        history = history[-CONTEXT_HISTORY_LIMIT:]

    payload = {"model": model, "prompt": full_prompt, "stream": True}
    reply = ""
    dots = ["", ".", "..", "..."]
    dot_index = 0
    start_time = time.time()

    async def update_progress():
        nonlocal dot_index
        while True:
            elapsed = time.time() - start_time
            formatted_text = f"Thinking... {elapsed:.1f}s{dots[dot_index]}"
            try:
                await progress_msg.edit_text(formatted_text + "\n" + reply, parse_mode="Markdown")
            except BadRequest:
                pass
            dot_index = (dot_index + 1) % len(dots)
            await asyncio.sleep(PROGRESS_UPDATE_INTERVAL)

    progress_task = asyncio.create_task(update_progress())
    try:
        final_text, elapsed = await stream_response(OLLAMA_URL, payload, user_id)
        reply = final_text
        reply = re.sub(r'[^\x00-\x7F]+', '', reply)
        reply = re.sub(r'```python\s*```', '', reply)
        print(f"Thinking time: {elapsed:.1f}s")
        final_text = f"{reply}\n✨ Generated in {elapsed:.1f}s"
        try:
            await progress_msg.edit_text(final_text, parse_mode="Markdown")
        except BadRequest:
            await progress_msg.edit_text(reply[:4096])

        # Update memory with new info
        new_info = extract_context_info(prompt, reply)
        memory.update(new_info)
        user_context[user_id] = {"memory": memory, "history": history}
        asyncio.create_task(save_context_async(user_context))
    finally:
        progress_task.cancel()
import aiohttp
import asyncio
import json
import re
import time
from config import OLLAMA_URL
from aiocache import cached, Cache

# Constants
RETRY_LIMIT = 5
TIMEOUT = 30
CACHE_TTL = 3600
MIN_STREAM_UPDATE_LENGTH = 150

def choose_model(prompt: str) -> str:
    prompt = prompt.lower()
    if any(word in prompt for word in ["code", "function", "class", "def", "script", "python"]):
        return "phi3:mini"
    elif any(word in prompt for word in ["complex", "detailed", "explain in depth"]):
        return "qwen2:1.5b"
    return "phi3:mini"

@cached(ttl=CACHE_TTL, cache=Cache.MEMORY, key_builder=lambda *args: f"{args[3]}:{args[2]['prompt']}")
async def stream_response(url: str, payload: dict, user_id: str) -> tuple[str, float]:
    reply = ""
    start_time = time.time()

    prompt_lower = payload["prompt"].lower()
    lang = "python"
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

    is_code = any(word in prompt_lower for word in ["code", "python", "java", "js", "php"])

    async with aiohttp.ClientSession() as session:
        models = [payload["model"], "phi3:mini", "qwen2:1.5b", "gemma:2b"]

        for model in models:
            payload["model"] = model
            for attempt in range(RETRY_LIMIT):
                try:
                    async with session.post(f"{url}/api/generate", json=payload, timeout=TIMEOUT) as response:
                        if response.status != 200:
                            continue

                        async for line in response.content:
                            if line:
                                try:
                                    chunk = json.loads(line.decode("utf-8").replace("data: ", ""))
                                    token = chunk.get("response", "")
                                    if token:
                                        token = re.sub(r'[^\x00-\x7F]+', '', token)
                                        reply += token
                                except json.JSONDecodeError:
                                    continue

                        final_text = reply[:4096] if reply.strip() else "Nada to say! Try again?"
                        elapsed = time.time() - start_time
                        if is_code:
                            final_text = re.sub(r'`', r'\`', final_text)
                            final_text = f"```{lang}\n{final_text.strip()}\n```"
                        else:
                            final_text = re.sub(r'```.*?\n.*?```', '', final_text, flags=re.DOTALL)
                            final_text = final_text.strip()
                        return final_text, elapsed

                except aiohttp.ClientConnectionError:
                    if attempt < RETRY_LIMIT - 1:
                        await asyncio.sleep(0.5)
                    continue
                except aiohttp.ClientResponseError:
                    break
                except asyncio.TimeoutError:
                    break

        return "AI’s taking a nap—try again later!", time.time() - start_time
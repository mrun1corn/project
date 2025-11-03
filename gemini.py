import aiohttp
import asyncio
import json
import os
import re
import time
import base64
import html

from telegram import Update
from telegram.ext import ContextTypes, Application, CommandHandler
from telegram.error import BadRequest

# Import necessary configurations from config.py
try:
    from config import ADMIN_CHAT_ID, GEMINI_API_KEY, BOT_TOKEN
except ImportError:
    ADMIN_CHAT_ID = 0
    GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_IS_MISSING"
    BOT_TOKEN = "YOUR_BOT_TOKEN_IS_MISSING"


# --- Mock for comm_checker (replace with your actual implementation) ---
from comm_checker import check_user_approval, command_states, check_command_enabled

# --- Constants ---
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
CONTEXT_FILE = "user_context.json"
# CONTEXT_HISTORY_LIMIT = 5 # This will now be managed by token count or number of turns
MAX_MESSAGE_LENGTH = 4096
PROGRESS_UPDATE_INTERVAL = 1.5
MAX_HISTORY_TURNS = 10 # Limit conversation history to 10 turns (user + model)

# Termbin settings
TERMBIN_HOST = "termbin.com"
TERMBIN_PORT = 9999

# --- Utility Functions ---

def sanitize_response(text: str) -> str:
    text = re.sub(r'\n\s*\n+', '\n\n', text.strip())
    return text

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

async def upload_to_termbin(text: str) -> str:
    """Upload text to termbin and return the URL."""
    try:
        # Method 1: Try direct socket connection
        reader, writer = await asyncio.open_connection(TERMBIN_HOST, TERMBIN_PORT)
        
        # Send the text
        writer.write(text.encode('utf-8'))
        await writer.drain()
        
        # Close the writing end to signal completion
        writer.write_eof()
        
        # Read the response (should be the URL)
        response_data = await asyncio.wait_for(reader.read(1024), timeout=10)
        
        # Close the connection
        writer.close()
        await writer.wait_closed()
        
        # Decode and clean the response
        url = response_data.decode('utf-8').strip()
        
        # Validate the URL format
        if url and (url.startswith('https://termbin.com/') or url.startswith('http://termbin.com/')):
            return url
        else:
            raise Exception(f"Invalid termbin response: '{url}'")
            
    except Exception as e:
        # Method 2: Try HTTP POST as fallback
        try:
            return await upload_to_termbin_http(text)
        except Exception as fallback_error:
            raise Exception(f"Socket method failed: {str(e)}, HTTP method failed: {str(fallback_error)}")

async def upload_to_termbin_http(text: str) -> str:
    """Alternative HTTP method to upload to termbin."""
    try:
        # Some termbin services accept HTTP POST
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://{TERMBIN_HOST}",
                data=text.encode('utf-8'),
                headers={'Content-Type': 'text/plain'},
                timeout=10
            ) as response:
                if response.status == 200:
                    url = await response.text()
                    url = url.strip()
                    if url and (url.startswith('https://termbin.com/') or url.startswith('http://termbin.com/')):
                        return url
                    else:
                        raise Exception(f"Invalid HTTP response: '{url}'")
                else:
                    raise Exception(f"HTTP request failed with status {response.status}")
    except Exception as e:
        # Method 3: Try subprocess as last resort
        return await upload_to_termbin_subprocess(text)

async def upload_to_termbin_subprocess(text: str) -> str:
    """Fallback method using subprocess to upload to termbin."""
    try:
        import subprocess
        import tempfile
        import os
        
        # Create a temporary file to avoid shell escaping issues
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:
            tmp_file.write(text)
            tmp_file_path = tmp_file.name
        
        try:
            # Use cat and nc command as shown in termbin documentation
            cmd = f"cat {tmp_file_path} | nc termbin.com 9999"
            
            # Run the command asynchronously
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
            
            if process.returncode == 0:
                url = stdout.decode('utf-8').strip()
                if url and (url.startswith('https://termbin.com/') or url.startswith('http://termbin.com/')):
                    return url
                else:
                    raise Exception(f"Invalid subprocess response: '{url}'")
            else:
                raise Exception(f"nc command failed: {stderr.decode('utf-8')}")
                
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
            
    except Exception as e:
        raise Exception(f"Subprocess upload failed: {str(e)}")

async def get_gemini_response(conversation_history: list, file_data: str = None, file_mime_type: str = None) -> tuple[str, float]:
    start = time.time()

    # The Gemini API expects 'contents' to be a list of messages
    # Each message has a 'role' (user/model) and 'parts')
    # The last message in 'contents' should be the current user's prompt
    
    # Construct the current user's message parts
    current_user_parts = []
    if conversation_history and conversation_history[-1].get("parts"):
        # Assuming the last message in history is the current user's text prompt
        current_user_parts.extend(conversation_history[-1]["parts"])

    if file_data and file_mime_type:
        current_user_parts.append({
            "inlineData": {"mimeType": file_mime_type, "data": file_data}
        })
    
    # Create the full payload with conversation history
    payload = {
        "contents": conversation_history[:-1] + [{"role": "user", "parts": current_user_parts}]
    }
    
    headers = {"Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(GEMINI_API_URL, json=payload, headers=headers, timeout=60) as resp:
                if resp.status != 200:
                    try:
                        error_details = await resp.text()
                    except Exception:
                        error_details = "Unknown error details"
                    return f"⚠️ Gemini API error: {resp.status} - {error_details}", 0.0
                
                data = await resp.json()
                
                candidates = data.get("candidates")
                if not candidates or not isinstance(candidates, list) or not candidates[0].get("content"):
                    safety_ratings = data.get("promptFeedback", {}).get("safetyRatings")
                    if safety_ratings:
                        for rating in safety_ratings:
                            if rating.get("blockReason"):
                                return f"⚠️ Gemini blocked response due to safety reasons: {rating.get('category')} - {rating.get('blockReason')}", 0.0
                    return f"⚠️ Unexpected Gemini response format or no content: {json.dumps(data, indent=2)}", 0.0
                
                reply = candidates[0]["content"]["parts"][0]["text"]
                elapsed = time.time() - start
                return reply.strip(), elapsed
        except aiohttp.client_exceptions.ClientConnectorError:
            return "⚠️ Network error connecting to Gemini API. Please check your internet connection.", 0.0
        except asyncio.TimeoutError:
            return "⚠️ Gemini API request timed out. Please try again.", 0.0
        except Exception as e:
            return f"⚠️ An unexpected error occurred while contacting Gemini: {str(e)}", 0.0

async def process_file(file_path: str, file_name: str) -> tuple[str, str]:
    try:
        with open(file_path, "rb") as f:
            binary_data = f.read()
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
    except Exception as e:
        return f"Error processing file: {str(e)}", None


# --- Command Handler ---

async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user_id = str(update.effective_user.id)
    
    user_id = update.effective_user.id # Get as int directly

    # Check user approval
    if not await check_user_approval(user_id):
        await message.reply_text("🔒 You're not approved to use this command.")
        return
    
    # Check if command is enabled
    if not await check_command_enabled('ai'):
        await message.reply_text("❌ AI command is currently disabled.")
        return

    # Load user context
    user_contexts = load_context()
    user_data = user_contexts.get(str(user_id), {"history": [], "memory": {}})
    conversation_history = user_data["history"]
    
    replied_message = message.reply_to_message
    file_data = None
    mime_type = None
    
    prompt_text = " ".join(context.args) if context.args else ""

    # Handle file attachments
    if replied_message:
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
                
                if "Error" in file_data: # process_file returns error string on failure
                    await message.reply_text(file_data)
                    return
                
                if not prompt_text:
                    prompt_text = "Describe the content of this file."
            except Exception as e:
                await message.reply_text(f"❌ Failed to process the attached file: {e}")
                return
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
        elif replied_message.text and not prompt_text:
            prompt_text = replied_message.text


    if not prompt_text and not (file_data and mime_type):
        await message.reply_text("Try: `/ai what is Python?` or reply to a file/image with a query.")
        return
    
    progress_msg = await message.reply_text("🧠 Thinking...")
    
    # Add current user message to history
    user_message_parts = []
    if prompt_text:
        user_message_parts.append({"text": prompt_text})
    if file_data and mime_type:
        user_message_parts.append({"inlineData": {"mimeType": mime_type, "data": file_data}})
    
    # Ensure there's at least one part in the user message
    if not user_message_parts:
        await message.reply_text("❌ No valid input provided for Gemini.")
        return

    conversation_history.append({"role": "user", "parts": user_message_parts})

    # Truncate history if it exceeds MAX_HISTORY_TURNS
    # Each turn consists of a user message and a model message.
    # So, MAX_HISTORY_TURNS * 2 messages in total.
    if len(conversation_history) > MAX_HISTORY_TURNS * 2:
        conversation_history = conversation_history[-(MAX_HISTORY_TURNS * 2):]
    
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
                break 
            dot_index = (dot_index + 1) % len(dots)
            await asyncio.sleep(PROGRESS_UPDATE_INTERVAL)

    progress_task = asyncio.create_task(update_progress())

    try:
        response_text, elapsed = await get_gemini_response(
            conversation_history=conversation_history,
            file_data=file_data, # Pass file data for the *current* turn
            file_mime_type=mime_type
        )
        
        # Prepare the response for display
        escaped_html = html.escape(response_text)
        sanitized_reply = sanitize_response(escaped_html)
        
        # Check if the response (with timing info) will fit in a Telegram message
        timing_info = f"\n\n✨ Generated in {elapsed:.1f}s"
        full_message = f"{sanitized_reply}{timing_info}"
        
        if len(full_message) > MAX_MESSAGE_LENGTH:
            # Response is too long for Telegram, upload to termbin
            try:
                await progress_msg.edit_text(f"📤 Response is long ({len(response_text)} chars), uploading to termbin...")
                termbin_url = await upload_to_termbin(response_text)
                
                # Send ONLY the termbin link (no preview text)
                final_message = f"📋 <b>Full response:</b> {termbin_url}{timing_info}"
                
                await progress_msg.edit_text(final_message, parse_mode="HTML")
                
            except Exception as e:
                # Fall back to truncation if termbin fails
                truncated_reply = sanitized_reply[:MAX_MESSAGE_LENGTH - 200] + f"...\n\n⚠️ Response was truncated (termbin upload failed: {str(e)})"
                await progress_msg.edit_text(f"{truncated_reply}{timing_info}", parse_mode="HTML")
        else:
            # Response fits in Telegram message, show it normally
            await progress_msg.edit_text(full_message, parse_mode="HTML")
        
        # Add model's response to history
        conversation_history.append({"role": "model", "parts": [{"text": response_text}]})
        
        # Save updated context
        user_data["history"] = conversation_history
        user_contexts[str(user_id)] = user_data
        asyncio.create_task(save_context_async(user_contexts))
        
    finally:
        progress_task.cancel()

# --- Register Handlers ---

def register_gemini_handlers(application):
    """Registers the /ai command handler with the Telegram Bot Application."""
    application.add_handler(CommandHandler("ai", ai_command))


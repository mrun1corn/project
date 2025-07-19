import os
import re
import yt_dlp
import asyncio
import aiofiles
import aiofiles.os
import uuid
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import RetryAfter, TimedOut
from comm_checker import command_states, check_user_approval

# Semaphores to limit concurrent downloads and uploads
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(10)
UPLOAD_SEMAPHORE = asyncio.Semaphore(3)  # Limit concurrent uploads to Telegram

# Ensure the 'downloads' directory exists
DOWNLOAD_DIR = 'downloads'
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def sanitize_filename(filename):
    """Sanitize filename to remove invalid characters."""
    return re.sub(r'[^\w\-_\. ]', '_', filename).strip()

async def _send_media_with_retry(context, chat_id, file_path, caption_or_title, media_type, max_retries=3):
    """Send media (audio or video) with retry logic, handling timeouts and rate limits."""
    for attempt in range(max_retries):
        try:
            print(f"Sending {media_type} to chat {chat_id}: {file_path} (attempt {attempt + 1})")
            
            if media_type == 'audio':
                send_func = context.bot.send_audio
                kwargs = {'title': caption_or_title}
            elif media_type == 'video':
                send_func = context.bot.send_video
                kwargs = {'caption': caption_or_title}
            else:
                raise ValueError("Invalid media_type. Must be 'audio' or 'video'.")

            with open(file_path, 'rb') as f: # Use synchronous open here
                await send_func(
                    chat_id=chat_id,
                    **{media_type: f}, # Pass file object directly
                    **kwargs
                )
            print(f"{media_type.capitalize()} sent successfully to chat {chat_id}")
            return True
        except RetryAfter as e:
            print(f"RetryAfter error: waiting {e.retry_after} seconds")
            await asyncio.sleep(e.retry_after)
        except TimedOut as e:
            print(f"Timeout error sending {media_type}: {e}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
        except asyncio.TimeoutError:
            print(f"Timeout after 60 seconds sending {media_type}")
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            print(f"Failed to send {media_type} (attempt {attempt + 1}): {e}")
            await asyncio.sleep(2 ** attempt)
    print(f"Failed to send {media_type} after {max_retries} attempts")
    return False



async def _perform_initial_checks(update: Update, context: ContextTypes.DEFAULT_TYPE, command_name: str, usage_message: str) -> bool:
    if not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return False

    if not command_states[command_name]:
        await update.message.reply_text(f"❌ The {command_name} command is currently disabled.")
        return False

    if not context.args:
        await update.message.reply_text(usage_message)
        return False
    return True

async def play_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /music command with concurrent download and playback."""
    progress_message = None
    audio_path = None # Initialize audio_path here
    task_id = str(uuid.uuid4())[:8]
    print(f"Starting /music task {task_id} for user {update.effective_user.id}")
    
    try:
        if not await _perform_initial_checks(update, context, 'music', "Usage: /music <song_name>"):
            return

        song_name = " ".join(context.args)
        unique_id = str(uuid.uuid4())
        progress_message = await update.message.reply_text(f"🔍 Searching for: _{song_name}_...", parse_mode='Markdown')

        async with DOWNLOAD_SEMAPHORE:
            try:
                # Extract info
                info_dict = await _run_ydl_operation(song_name)

                if 'entries' in info_dict:
                    info_dict = info_dict['entries'][0]

                audio_format = next(
                    (f for f in info_dict['formats'] if f.get('acodec') != 'none' and f.get('vcodec') == 'none' and f.get('ext') in ['mp3', 'm4a', 'ogg', 'opus', 'webm']),
                    None
                )

                if not audio_format:
                    await progress_message.edit_text("❌ No suitable audio format found.")
                    return

                file_size = audio_format.get('filesize') or (audio_format.get('tbr', 0) * 1000 / 8) * info_dict.get('duration', 0)
                if not file_size:
                    await progress_message.edit_text("❌ Could not estimate file size.")
                    return

                if file_size > 50 * 1024 * 1024:  # Increased to 50 MB limit for audio
                    await progress_message.edit_text(f"❌ File too large ({file_size/(1024*1024):.1f} MB). Use an external downloader.")
                    return

                await progress_message.edit_text("⬇️ Downloading audio...")

                # Download audio
                sanitized_title = sanitize_filename(info_dict['title'])
                audio_file_path_template = os.path.join(DOWNLOAD_DIR, f"{sanitized_title}_{unique_id}.%(ext)s")
                await _run_ydl_operation(info_dict['webpage_url'], download=True, output_path=audio_file_path_template)

                # Find the downloaded file
                downloaded_files = await aiofiles.os.listdir(DOWNLOAD_DIR)
                downloaded_file = next(
                    (f for f in downloaded_files if f.startswith(f"{sanitized_title}_{unique_id}")), None
                )

                if downloaded_file:
                    audio_path = os.path.join(DOWNLOAD_DIR, downloaded_file)
                    async with UPLOAD_SEMAPHORE:
                        success = await _send_media_with_retry(context, update.effective_chat.id, audio_path, sanitized_title, 'audio')
                    if success:
                        await progress_message.delete()
                    else:
                        await progress_message.edit_text("❌ Failed to send audio after retries.")

                else:
                    await progress_message.edit_text(f"❌ Download failed. Files found: {', '.join(downloaded_files)}")

            except yt_dlp.utils.DownloadError as e:
                print(f"Download error in task {task_id}: {e}")
                await progress_message.edit_text(f"❌ Download error: `{str(e)}`", parse_mode='Markdown')
            except Exception as e:
                print(f"Error in task {task_id}: {e}")
                await progress_message.edit_text(f"❌ Error: `{str(e)}`", parse_mode='Markdown')

    except Exception as e:
        print(f"Critical error in task {task_id}: {e}")
        if progress_message:
            await progress_message.edit_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
    finally:
        if audio_path and await aiofiles.os.path.exists(audio_path):
            try:
                await aiofiles.os.remove(audio_path)
                print(f"Cleaned up audio file: {audio_path}")
            except Exception as e:
                print(f"Error cleaning up audio file {audio_path}: {e}")
        if progress_message:
            try:
                await progress_message.delete()
            except Exception as e:
                print(f"Error deleting progress message in task {task_id}: {e}")
        print(f"Completed /music task {task_id}")

async def _run_ydl_operation(query, download=False, output_path=None, is_video=False):
    """Run yt-dlp extract_info or download in a separate thread with consolidated options."""
    if is_video:
        format_str = 'bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/mp4'
    else:
        # Prioritize m4a, opus, then best audio
        format_str = 'bestaudio[ext=m4a]/bestaudio[ext=opus]/bestaudio/best'

    ydl_opts = {
        'format': format_str,
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch',
    }

    if download:
        ydl_opts['outtmpl'] = output_path
        print(f"Downloading: {query} to {output_path}")
    else:
        ydl_opts['skip_download'] = True
        print(f"Extracting info for: {query}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        if download:
            await asyncio.to_thread(ydl.download, [query])
            print(f"Download completed: {output_path}")
            return True # Indicate success
        else:
            result = await asyncio.to_thread(ydl.extract_info, query, download=False)
            print(f"Info extracted for: {query}")
            return result

async def play_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /video command with concurrent download and playback."""
    progress_message = None
    video_path = None # Initialize video_path here
    task_id = str(uuid.uuid4())[:8]
    print(f"Starting /video task {task_id} for user {update.effective_user.id}")
    
    try:
        if not await _perform_initial_checks(update, context, 'video', "Usage: /video <video_name>"):
            return

        video_name = " ".join(context.args)
        unique_id = str(uuid.uuid4())
        progress_message = await update.message.reply_text(f"🔍 Searching for: _{video_name}_...", parse_mode='Markdown')

        sanitized_video_name = sanitize_filename(video_name)
        video_file_path_template = os.path.join(DOWNLOAD_DIR, f"{sanitized_video_name}_{unique_id}.%(ext)s")

        async with DOWNLOAD_SEMAPHORE:
            # Always attempt to download, as caching is not explicitly handled here
            try:
                # Extract info
                info_dict = await _run_ydl_operation(video_name, is_video=True)

                if 'entries' in info_dict:
                    info_dict = info_dict['entries'][0]

                file_size = info_dict.get('filesize') or (info_dict.get('tbr', 0) * 1000 / 8) * info_dict.get('duration', 0)
                if file_size and file_size > 50 * 1024 * 1024:  # Increased to 50 MB limit for video
                    await progress_message.edit_text(f"❌ Video too large ({file_size/(1024*1024):.1f} MB).")
                    return

                await progress_message.edit_text("⬇️ Downloading video...")

                # Download video
                await _run_ydl_operation(info_dict['webpage_url'], download=True, output_path=video_file_path_template, is_video=True)

                # Find the downloaded file
                downloaded_files = await aiofiles.os.listdir(DOWNLOAD_DIR)
                downloaded_file = next(
                    (f for f in downloaded_files if f.startswith(f"{sanitized_video_name}_{unique_id}")), None
                )

                if downloaded_file:
                    video_path = os.path.join(DOWNLOAD_DIR, downloaded_file)
                    await progress_message.edit_text("📤 Sending video...")
                    async with UPLOAD_SEMAPHORE:
                        success = await _send_media_with_retry(context, update.effective_chat.id, video_path, sanitized_video_name, 'video')
                    if success:
                        await progress_message.delete()
                    else:
                        await progress_message.edit_text("❌ Failed to send video after retries.")
                else:
                    await progress_message.edit_text("❌ Video file not found after download.")

            except yt_dlp.utils.DownloadError as e:
                print(f"Download error in task {task_id}: {e}")
                await progress_message.edit_text(f"❌ Download error: `{str(e)}`", parse_mode='Markdown')
                return
            except Exception as e:
                print(f"Error in task {task_id}: {e}")
                await progress_message.edit_text(f"❌ Error: `{str(e)}`", parse_mode='Markdown')
                return

    except Exception as e:
        print(f"Critical error in task {task_id}: {e}")
        if progress_message:
            await progress_message.edit_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
    finally:
        if video_path and await aiofiles.os.path.exists(video_path):
            try:
                await aiofiles.os.remove(video_path)
                print(f"Cleaned up video file: {video_path}")
            except Exception as e:
                print(f"Error cleaning up video file {video_path}: {e}")
        if progress_message:
            try:
                await progress_message.delete()
            except Exception as e:
                print(f"Error deleting progress message in task {task_id}: {e}")
        print(f"Completed /video task {task_id}")
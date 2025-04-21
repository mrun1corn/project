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

async def send_audio_with_retry(context, chat_id, audio_file_path, title, max_retries=3):
    """Send audio with retry logic, handling timeouts and rate limits."""
    for attempt in range(max_retries):
        try:
            print(f"Sending audio to chat {chat_id}: {audio_file_path} (attempt {attempt + 1})")
            await asyncio.wait_for(
                context.bot.send_audio(
                    chat_id=chat_id,
                    audio=open(audio_file_path, 'rb'),
                    title=title
                ),
                timeout=60  # Enforce 60-second timeout
            )
            print(f"Audio sent successfully to chat {chat_id}")
            return True
        except RetryAfter as e:
            print(f"RetryAfter error: waiting {e.retry_after} seconds")
            await asyncio.sleep(e.retry_after)
        except TimedOut as e:
            print(f"Timeout error sending audio: {e}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
        except asyncio.TimeoutError:
            print(f"Timeout after 60 seconds sending audio")
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            print(f"Failed to send audio (attempt {attempt + 1}): {e}")
            await asyncio.sleep(2 ** attempt)
    print(f"Failed to send audio after {max_retries} attempts")
    return False

async def send_video_with_retry(context, chat_id, video_file_path, caption, max_retries=3):
    """Send video with retry logic, handling timeouts and rate limits."""
    for attempt in range(max_retries):
        try:
            print(f"Sending video to chat {chat_id}: {video_file_path} (attempt {attempt + 1})")
            await asyncio.wait_for(
                context.bot.send_video(
                    chat_id=chat_id,
                    video=open(video_file_path, 'rb'),
                    caption=caption
                ),
                timeout=60  # Enforce 60-second timeout
            )
            print(f"Video sent successfully to chat {chat_id}")
            return True
        except RetryAfter as e:
            print(f"RetryAfter error: waiting {e.retry_after} seconds")
            await asyncio.sleep(e.retry_after)
        except TimedOut as e:
            print(f"Timeout error sending video: {e}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
        except asyncio.TimeoutError:
            print(f"Timeout after 60 seconds sending video")
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            print(f"Failed to send video (attempt {attempt + 1}): {e}")
            await asyncio.sleep(2 ** attempt)
    print(f"Failed to send video after {max_retries} attempts")
    return False

async def run_ydl_extract_info(song_name):
    """Run yt-dlp extract_info in a separate thread."""
    ydl_opts_info = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'skip_download': True,
        'default_search': 'ytsearch',
    }
    print(f"Extracting info for: {song_name}")
    with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
        result = await asyncio.to_thread(ydl.extract_info, song_name, download=False)
        print(f"Info extracted for: {song_name}")
        return result

async def run_ydl_download(url, output_path):
    """Run yt-dlp download in a separate thread."""
    ydl_opts_download = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'noplaylist': True,
        'quiet': True,
    }
    print(f"Downloading: {url} to {output_path}")
    with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
        await asyncio.to_thread(ydl.download, [url])
    print(f"Download completed: {output_path}")

async def play_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /music command with concurrent download and playback."""
    progress_message = None
    task_id = str(uuid.uuid4())[:8]
    print(f"Starting /music task {task_id} for user {update.effective_user.id}")
    
    try:
        if not await check_user_approval(update.effective_user.id):
            await update.message.reply_text("❌ You are not approved to use this command.")
            return

        if not command_states['music']:
            await update.message.reply_text("❌ The music command is currently disabled.")
            return    

        if not context.args:
            await update.message.reply_text("Usage: /music <song_name>")
            return

        song_name = " ".join(context.args)
        unique_id = str(uuid.uuid4())
        progress_message = await update.message.reply_text(f"🔍 Searching for: _{song_name}_...", parse_mode='Markdown')

        async with DOWNLOAD_SEMAPHORE:
            try:
                # Extract info
                info_dict = await run_ydl_extract_info(song_name)

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

                if file_size > 15 * 1024 * 1024:  # Stricter 15 MB limit for audio
                    await progress_message.edit_text(f"❌ File too large ({file_size/(1024*1024):.1f} MB). Use an external downloader.")
                    return

                await progress_message.edit_text("⬇️ Downloading audio...")

                # Download audio
                sanitized_title = sanitize_filename(info_dict['title'])
                audio_file_path = os.path.join(DOWNLOAD_DIR, f"{sanitized_title}_{unique_id}.%(ext)s")
                await run_ydl_download(info_dict['webpage_url'], audio_file_path)

                # Find the downloaded file
                downloaded_files = await aiofiles.os.listdir(DOWNLOAD_DIR)
                downloaded_file = next(
                    (f for f in downloaded_files if f.startswith(f"{sanitized_title}_{unique_id}")), None
                )

                if downloaded_file:
                    audio_path = os.path.join(DOWNLOAD_DIR, downloaded_file)
                    async with UPLOAD_SEMAPHORE:
                        success = await send_audio_with_retry(context, update.effective_chat.id, audio_path, sanitized_title)
                    if success:
                        await progress_message.delete()
                    else:
                        await progress_message.edit_text("❌ Failed to send audio after retries.")

                    # Clean up
                    if await aiofiles.os.path.exists(audio_path):
                        await aiofiles.os.remove(audio_path)
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
        print(f"Completed /music task {task_id}")

async def run_ydl_video_extract_info(video_name):
    """Run yt-dlp extract_info for video in a separate thread."""
    ydl_opts_info = {
        'format': 'bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/mp4',
        'noplaylist': True,
        'quiet': True,
        'skip_download': True,
        'default_search': 'ytsearch',
    }
    print(f"Extracting video info for: {video_name}")
    with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
        result = await asyncio.to_thread(ydl.extract_info, video_name, download=False)
        print(f"Video info extracted for: {video_name}")
        return result

async def run_ydl_video_download(url, output_path):
    """Run yt-dlp download for video in a separate thread."""
    ydl_opts_download = {
        'format': 'bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/mp4',
        'outtmpl': output_path,
        'noplaylist': True,
        'quiet': True,
    }
    print(f"Downloading video: {url} to {output_path}")
    with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
        await asyncio.to_thread(ydl.download, [url])
    print(f"Video download completed: {output_path}")

async def play_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /video command with concurrent download and playback."""
    progress_message = None
    task_id = str(uuid.uuid4())[:8]
    print(f"Starting /video task {task_id} for user {update.effective_user.id}")
    
    try:
        if not await check_user_approval(update.effective_user.id):
            await update.message.reply_text("❌ You are not approved to use this command.")
            return

        if not command_states['video']:
            await update.message.reply_text("❌ The video command is currently disabled.")
            return    

        if not context.args:
            await update.message.reply_text("Usage: /video <video_name>")
            return

        video_name = " ".join(context.args)
        unique_id = str(uuid.uuid4())
        progress_message = await update.message.reply_text(f"🔍 Searching for: _{video_name}_...", parse_mode='Markdown')

        sanitized_video_name = sanitize_filename(video_name)
        video_file_path = os.path.join(DOWNLOAD_DIR, f"{sanitized_video_name}_{unique_id}.mp4")

        async with DOWNLOAD_SEMAPHORE:
            if await aiofiles.os.path.exists(video_file_path):
                await progress_message.edit_text("📦 Found cached video. Sending...")
            else:
                try:
                    # Extract info
                    info_dict = await run_ydl_video_extract_info(video_name)

                    if 'entries' in info_dict:
                        info_dict = info_dict['entries'][0]

                    file_size = info_dict.get('filesize') or (info_dict.get('tbr', 0) * 1000 / 8) * info_dict.get('duration', 0)
                    if file_size and file_size > 40 * 1024 * 1024:  # Stricter 40 MB limit for video
                        await progress_message.edit_text(f"❌ Video too large ({file_size/(1024*1024):.1f} MB).")
                        return

                    await progress_message.edit_text("⬇️ Downloading video...")

                    # Download video
                    await run_ydl_video_download(info_dict['webpage_url'], video_file_path)

                    await progress_message.edit_text("📤 Sending video...")

                except yt_dlp.utils.DownloadError as e:
                    print(f"Download error in task {task_id}: {e}")
                    await progress_message.edit_text(f"❌ Download error: `{str(e)}`", parse_mode='Markdown')
                    return
                except Exception as e:
                    print(f"Error in task {task_id}: {e}")
                    await progress_message.edit_text(f"❌ Error: `{str(e)}`", parse_mode='Markdown')
                    return

            if await aiofiles.os.path.exists(video_file_path):
                async with UPLOAD_SEMAPHORE:
                    success = await send_video_with_retry(context, update.effective_chat.id, video_file_path, sanitized_video_name)
                if success:
                    await progress_message.delete()
                    if await aiofiles.os.path.exists(video_file_path):
                        await aiofiles.os.remove(video_file_path)
                else:
                    await progress_message.edit_text("❌ Failed to send video after retries.")
            else:
                await progress_message.edit_text("❌ Video file not found after download.")

    except Exception as e:
        print(f"Critical error in task {task_id}: {e}")
        if progress_message:
            await progress_message.edit_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
    finally:
        print(f"Completed /video task {task_id}")
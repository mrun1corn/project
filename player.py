import os
import re
import yt_dlp
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from comm_checker import command_states, check_user_approval

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure the 'downloads' directory exists
DOWNLOAD_DIR = 'downloads'
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def sanitize_filename(filename):
    return re.sub(r'[^\w\-_\. ]', '_', filename).strip()

async def send_audio_with_retry(context, chat_id, audio_file_path, title, max_retries=3):
    for attempt in range(max_retries):
        try:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=open(audio_file_path, 'rb'),
                title=title,
            )
            return True  # Success
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} to send audio failed: {e}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
    return False  # All retries failed

async def send_video_with_retry(context, chat_id, video_file_path, caption, max_retries=3):
    for attempt in range(max_retries):
        try:
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(video_file_path, 'rb'),
                caption=caption,
            )
            return True  # Success
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} to send video failed: {e}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
    return False  # All retries failed

async def play_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    progress_message = None
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
        progress_message = await update.message.reply_text(f"🔍 Searching for: _{song_name}_...", parse_mode='Markdown')

        ydl_opts_info = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'skip_download': True,
            'default_search': 'ytsearch',
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info_dict = ydl.extract_info(song_name, download=False)

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

            if file_size > 20 * 1024 * 1024:  # 20 MB limit
                await progress_message.edit_text(f"❌ File too large ({file_size/(1024*1024):.1f} MB). Use an external downloader.")
                return

            await progress_message.edit_text("⬇️ Downloading audio...")

            ydl_opts_download = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
                'noplaylist': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                ydl.download([info_dict['webpage_url']])

            downloaded_files = os.listdir(DOWNLOAD_DIR)
            downloaded_file = next((f for f in downloaded_files if f.endswith(('.mp3', '.m4a', '.ogg', '.opus', '.webm'))), None)

            if downloaded_file:
                sanitized_file = sanitize_filename(downloaded_file)
                old_path = os.path.join(DOWNLOAD_DIR, downloaded_file)
                new_path = os.path.join(DOWNLOAD_DIR, sanitized_file)
                os.rename(old_path, new_path)

                # Send audio and delete progress message
                success = await send_audio_with_retry(context, update.effective_chat.id, new_path, os.path.splitext(sanitized_file)[0])
                if success:
                    await progress_message.delete()
                else:
                    await progress_message.edit_text("❌ Failed to send audio after retries.")

                os.remove(new_path)
            else:
                await progress_message.edit_text(f"❌ Download failed. Files found: {', '.join(downloaded_files)}")

        except yt_dlp.utils.DownloadError as e:
            await progress_message.edit_text(f"❌ Download error: `{str(e)}`", parse_mode='Markdown')
            logger.error(f"DownloadError: {e}")
        except Exception as e:
            await progress_message.edit_text(f"❌ Error: `{str(e)}`", parse_mode='Markdown')
            logger.error(f"Unexpected error: {e}")

    except Exception as e:
        if progress_message:
            await progress_message.edit_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
        logger.error(f"Critical error: {e}")

async def play_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    progress_message = None
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
        progress_message = await update.message.reply_text(f"🔍 Searching for: _{video_name}_...", parse_mode='Markdown')

        sanitized_video_name = sanitize_filename(video_name)
        video_file_path = os.path.join(DOWNLOAD_DIR, f"{sanitized_video_name}.mp4")

        if os.path.exists(video_file_path):
            await progress_message.edit_text("📦 Found cached video. Sending...")
        else:
            ydl_opts_info = {
                'format': 'bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/mp4',
                'noplaylist': True,
                'quiet': True,
                'skip_download': True,
                'default_search': 'ytsearch',
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                    info_dict = ydl.extract_info(video_name, download=False)

                if 'entries' in info_dict:
                    info_dict = info_dict['entries'][0]

                file_size = info_dict.get('filesize') or (info_dict.get('tbr', 0) * 1000 / 8) * info_dict.get('duration', 0)
                if file_size and file_size > 50 * 1024 * 1024:  # 50 MB limit
                    await progress_message.edit_text(f"❌ Video too large ({file_size/(1024*1024):.1f} MB).")
                    return

                await progress_message.edit_text("⬇️ Downloading video...")

                ydl_opts_download = {
                    'format': 'bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/mp4',
                    'outtmpl': video_file_path,
                    'noplaylist': True,
                }

                with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                    ydl.download([info_dict['webpage_url']])

                await progress_message.edit_text("📤 Sending video...")

            except yt_dlp.utils.DownloadError as e:
                await progress_message.edit_text(f"❌ Download error: `{str(e)}`", parse_mode='Markdown')
                logger.error(f"DownloadError: {e}")
                return
            except Exception as e:
                await progress_message.edit_text(f"❌ Error: `{str(e)}`", parse_mode='Markdown')
                logger.error(f"Unexpected error: {e}")
                return

        if os.path.exists(video_file_path):
            success = await send_video_with_retry(context, update.effective_chat.id, video_file_path, sanitized_video_name)
            if success:
                await progress_message.delete()
                os.remove(video_file_path)
            else:
                await progress_message.edit_text("❌ Failed to send video after retries.")
        else:
            await progress_message.edit_text("❌ Video file not found after download.")

    except Exception as e:
        if progress_message:
            await progress_message.edit_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Critical error: `{str(e)}`", parse_mode='Markdown')
        logger.error(f"Critical error: {e}")
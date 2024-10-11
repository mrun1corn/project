import os
import re
import yt_dlp
import asyncio  # Import asyncio for sleep function
from telegram import Update
from telegram.ext import ContextTypes
from comm_checker import command_states, check_user_approval

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
            return  # If sending is successful, exit the loop
        except Exception as e:
            print(f"Attempt {attempt + 1} to send audio failed: {e}")
            await asyncio.sleep(1)  # Wait before retrying
    raise Exception("Failed to send audio after multiple attempts.")

async def send_video_with_retry(context, chat_id, video_file_path, caption, max_retries=3):
    for attempt in range(max_retries):
        try:
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(video_file_path, 'rb'),
                caption=caption,
            )
            return  # If sending is successful, exit the loop
        except Exception as e:
            print(f"Attempt {attempt + 1} to send video failed: {e}")
            await asyncio.sleep(1)  # Wait before retrying
    raise Exception("Failed to send video after multiple attempts.")

async def play_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if not await check_user_approval(update.effective_user.id):
            await update.message.reply_text("You are not approved to use this command.")
            return

        if not command_states['music']:
            await update.message.reply_text("The music command is currently disabled.")
            return    

        if len(context.args) == 0:
            await update.message.reply_text("Usage: /music <song_name>")
            return

        song_name = " ".join(context.args)
        
        progress_message = await update.message.reply_text(f"Searching for: {song_name}")
        
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
                await progress_message.edit_text("Error: No suitable audio format found.")
                return

            file_size = audio_format.get('filesize', None)
            duration = info_dict.get('duration', 0)
            bitrate = audio_format.get('tbr', None)

            if not file_size and bitrate and duration:
                file_size = (bitrate * 1000 / 8) * duration

            if not file_size:
                await progress_message.edit_text("Error: Could not retrieve file size.")
                return

            if file_size > 20 * 1024 * 1024:
                await progress_message.edit_text(f"The audio file size is: {file_size / (1024 * 1024):.2f} MB. Please use an external downloader.")
                return

            await progress_message.edit_text(f"File size is acceptable: {file_size / (1024 * 1024):.2f} MB. Downloading...")

            ydl_opts_download = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
                'noplaylist': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                ydl.download([info_dict['webpage_url']])

            downloaded_files = os.listdir(DOWNLOAD_DIR)
            print(f"Files in downloads directory: {downloaded_files}")

            downloaded_file = next((f for f in downloaded_files if f.endswith(('.mp3', '.m4a', '.ogg', '.opus', '.webm'))), None)

            if downloaded_file:
                sanitized_file = sanitize_filename(downloaded_file)
                os.rename(os.path.join(DOWNLOAD_DIR, downloaded_file), os.path.join(DOWNLOAD_DIR, sanitized_file))

                title_without_extension, _ = os.path.splitext(sanitized_file)

                await send_audio_with_retry(context, update.effective_chat.id, os.path.join(DOWNLOAD_DIR, sanitized_file), title_without_extension)

                os.remove(os.path.join(DOWNLOAD_DIR, sanitized_file))
            else:
                await progress_message.edit_text("Error: Audio file not found after download. Files in directory: " + ", ".join(downloaded_files))

        except Exception as e:
            await progress_message.edit_text(f"Error occurred: {e}")
            print(f"Error in play_audio: {e}")

    except OSError as e:
        await update.message.reply_text(f"OS Error: {e}")
        print(f"OS Error in play_audio: {e}")

    except Exception as e:
        await update.message.reply_text(f"An unexpected error occurred: {e}")
        print(f"Unexpected error: {e}")

async def play_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if len(context.args) == 0:
            await update.message.reply_text("Usage: /video <video_name>")
            return

        video_name = " ".join(context.args)
        progress_message = await update.message.reply_text(f"Searching for: {video_name}")

        sanitized_video_name = sanitize_filename(video_name)
        video_file_path = os.path.join(DOWNLOAD_DIR, f"{sanitized_video_name}.mp4")

        if os.path.exists(video_file_path):
            await progress_message.edit_text("Video file already exists. Sending...")
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

                file_size = info_dict.get('filesize', None)
                if file_size and file_size > 50 * 1024 * 1024:
                    await progress_message.edit_text(f"The video file size is: {file_size / (1024 * 1024):.2f} MB. Please use an external downloader.")
                    return

                ydl_opts_download = {
                    'format': 'bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/mp4',
                    'outtmpl': video_file_path,
                    'noplaylist': True,
                }

                with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                    ydl.download([info_dict['webpage_url']])

                await progress_message.edit_text("Download complete. Sending video...")

            except Exception as e:
                await progress_message.edit_text(f"Error occurred during download: {e}")
                return

        caption_without_extension = sanitized_video_name

        await send_video_with_retry(context, update.effective_chat.id, video_file_path, caption_without_extension)

        os.remove(video_file_path)

    except OSError as e:
        await update.message.reply_text(f"OS Error: {e}")
        print(f"OS Error in play_video: {e}")

    except Exception as e:
        await update.message.reply_text(f"An unexpected error occurred: {e}")
        print(f"Unexpected error: {e}")

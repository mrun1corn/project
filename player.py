import os
import re
import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes
from comm_checker import command_states, check_user_approval

# Ensure the 'downloads' directory exists
DOWNLOAD_DIR = 'downloads'
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def sanitize_filename(filename):
    # Replace problematic characters and strip excess whitespace
    return re.sub(r'[^\w\-_\. ]', '_', filename).strip()

async def play_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        # Check if the user is approved
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
        
        # Reply to the user's command
        progress_message = await update.message.reply_text(f"Searching for: {song_name}")
        
        # yt-dlp options for getting metadata without downloading
        ydl_opts_info = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'skip_download': True,
            'default_search': 'ytsearch',  # Use YouTube search by default
        }

        try:
            # Get metadata about the song (including file size)
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info_dict = ydl.extract_info(song_name, download=False)

            if 'entries' in info_dict:
                # Extract the first result from the search
                info_dict = info_dict['entries'][0]

            # Extract audio format and file size information
            if 'formats' in info_dict:
                # Get the first available audio format that Telegram supports
                audio_format = next(
                    (f for f in info_dict['formats'] if f.get('acodec') != 'none' and f.get('vcodec') == 'none' and f.get('ext') in ['mp3', 'm4a', 'ogg', 'opus', 'webm']),
                    None
                )

                if not audio_format:
                    await progress_message.edit_text("Error: No suitable audio format found.")
                    return

                file_size = audio_format.get('filesize', None)
                duration = info_dict.get('duration', 0)  # Duration in seconds
                bitrate = audio_format.get('tbr', None)  # Average bitrate in kbps

                # Estimate file size if missing
                if not file_size and bitrate and duration:
                    file_size = (bitrate * 1000 / 8) * duration  # Estimate based on bitrate and duration

                if not file_size:
                    await progress_message.edit_text("Error: Could not retrieve file size.")
                    return

                # Check if the file exceeds the 20 MB limit
                if file_size > 20 * 1024 * 1024:  # 20 MB limit
                    await progress_message.edit_text(f"The audio file size is: {file_size / (1024 * 1024):.2f} MB. Please use external downloader.")
                    return

                # Now proceed to download the file since size is acceptable
                await progress_message.edit_text(f"File size is acceptable: {file_size / (1024 * 1024):.2f} MB. Downloading...")

                # Download audio using yt-dlp
                ydl_opts_download = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
                    'noplaylist': True,
                    'concurrent_frag_downloads': 3,
                    'http_chunk_size': 1024 * 1024,  # 1 MB chunks
                    'timeout': 60,
                    'retries': 3,
                }

                with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                    ydl.download([info_dict['webpage_url']])

                # Check and list all files in the downloads directory to debug the issue
                downloaded_files = os.listdir(DOWNLOAD_DIR)
                print(f"Files in downloads directory: {downloaded_files}")

                # Find and sanitize an audio file that Telegram supports (checking multiple extensions)
                downloaded_file = next((f for f in downloaded_files if f.endswith(('.mp3', '.m4a', '.ogg', '.opus', '.webm'))), None)

                if downloaded_file:
                    sanitized_file = sanitize_filename(downloaded_file)
                    os.rename(os.path.join(DOWNLOAD_DIR, downloaded_file), os.path.join(DOWNLOAD_DIR, sanitized_file))

                    # Strip the file extension for the title
                    title_without_extension, _ = os.path.splitext(sanitized_file)

                    # Send the downloaded and sanitized audio file with the title excluding extension
                    await context.bot.send_audio(
                        chat_id=update.effective_chat.id,
                        audio=open(f'{DOWNLOAD_DIR}/{sanitized_file}', 'rb'),
                        title=title_without_extension,  # Only the name without extension
                    )
                    os.remove(f'{DOWNLOAD_DIR}/{sanitized_file}')  # Clean up after sending
                else:
                    await progress_message.edit_text("Error: Audio file not found after download. Files in directory: " + ", ".join(downloaded_files))

        except Exception as e:
            await progress_message.edit_text(f"Error occurred: {e}")
            print(f"Error in play_audio: {e}")

    except OSError as e:
        # Handle I/O errors
        await update.message.reply_text(f"OS Error: {e}")
        print(f"OS Error in play_audio: {e}")

    except Exception as e:
        await update.message.reply_text(f"An unexpected error occurred: {e}")
        print(f"Unexpected error: {e}")

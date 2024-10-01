import os
import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes
from comm_checker import command_states, check_user_approval

async def play_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    progress_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text=f"Searching for: {song_name}", 
        reply_to_message_id=update.message.message_id
    )

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
            audio_format = next((f for f in info_dict['formats'] if f['format_id'] == '251'), None)

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

            # Check if the file exceeds the 50 MB limit
            if file_size > 50 * 1024 * 1024:  # 50 MB limit
                await progress_message.edit_text(f"The audio file size is: {file_size / (1024 * 1024):.2f} MB. Please use externel downloader.")
                return

            # Now proceed to download the file since size is acceptable
            await progress_message.edit_text(f"File size is acceptable. Downloading...")

            # Download audio using yt-dlp
            ydl_opts_download = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'noplaylist': True,
                'concurrent_frag_downloads': 3,
                'http_chunk_size': 1024 * 1024,  # 1 MB chunks
                'timeout': 60,
                'retries': 3,
            }

            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                ydl.download([info_dict['webpage_url']])

            # Send the downloaded audio file
            downloaded_file = next((f for f in os.listdir('downloads') if f.endswith(('.webm', '.m4a', '.opus'))), None)
            if downloaded_file:
                file_title = os.path.splitext(downloaded_file)[0]
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id, 
                    audio=open(f'downloads/{downloaded_file}', 'rb'), 
                    title=file_title,
                    reply_to_message_id=update.message.message_id  # Reply to original command
                )
                os.remove(f'downloads/{downloaded_file}')  # Clean up after sending
            else:
                await progress_message.edit_text("Error: Audio file not found after download.")

    except Exception as e:
        await progress_message.edit_text(f"Error occurred: {e}")
        print(f"Error in play_audio: {e}")

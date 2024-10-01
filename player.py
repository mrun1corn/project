import os
import time
import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes
from comm_checker import command_states, check_user_approval  # Make sure to import check_user_approval

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
    progress_message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Searching for: {song_name}")

    # Configure yt-dlp options to download the best available audio format directly (without conversion)
    ydl_opts = {
        'format': 'bestaudio/best',  # Download the best available audio format
        'outtmpl': f'downloads/%(title)s.%(ext)s',  # Save the file with title and extension
        'default_search': 'ytsearch',
        'noplaylist': True,
        'progress_hooks': [lambda d: update_progress(progress_message, d, context)],  # Progress update
        'concurrent_frag_downloads': 3,
        'http_chunk_size': 1024 * 1024,  # 1 MB chunks
        'timeout': 60,  # Timeout of 60 seconds
        'retries': 3,   # Retry if download fails
    }

    try:
        # Search for the audio and download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([song_name])
        
        # Notify the user after download
        await progress_message.edit_text("Download complete! Sending audio...")

        # Find the downloaded audio file (it could be .webm or .m4a, etc.)
        downloaded_file = next((f for f in os.listdir('downloads') if f.endswith(('.webm', '.m4a', '.opus'))), None)
        if downloaded_file:
            # Send the audio file as it is
            await context.bot.send_audio(chat_id=update.effective_chat.id, audio=open(f'downloads/{downloaded_file}', 'rb'))
            os.remove(f'downloads/{downloaded_file}')  # Clean up after sending
        else:
            await progress_message.edit_text("Error: Audio file not found after download.")
    
    except Exception as e:
        await progress_message.edit_text(f"Could not find or download the audio: {e}")
        print(f"Error in play_audio: {e}")

# Enhanced progress update function
last_update_time = 0

def update_progress(progress_message, d, context):  # Accept context as an argument
    global last_update_time
    current_time = time.time()

    if d['status'] == 'downloading':
        if 'downloaded_bytes' in d and 'total_bytes' in d and d['total_bytes'] > 0:
            percent = d['downloaded_bytes'] / d['total_bytes'] * 100
            
            # Ensure meaningful updates: Update only when progress is significant and after 2 seconds
            if percent > 1 and (current_time - last_update_time) > 2:
                elapsed_time = current_time - d.get('start_time', current_time)
                
                # Calculate estimated remaining time only if there's progress
                if d['downloaded_bytes'] > 0:
                    estimated_total_time = elapsed_time / (d['downloaded_bytes'] / d['total_bytes'])
                    estimated_remaining_time = estimated_total_time - elapsed_time

                    # Format the remaining time
                    remaining_minutes, remaining_seconds = divmod(estimated_remaining_time, 60)
                    remaining_time_str = f"{int(remaining_minutes)}m {int(remaining_seconds)}s" if estimated_remaining_time > 0 else "Calculating..."

                    # Calculate download speed
                    download_speed = d['downloaded_bytes'] / elapsed_time if elapsed_time > 0 else 0
                    download_speed_str = f"{download_speed / (1024 * 1024):.2f} MB/s" if download_speed > 0 else "Calculating..."

                    # Update progress message with formatted data
                    context.application.create_task(
                        progress_message.edit_text(
                            f"Downloading... {percent:.2f}%\n"
                            f"Download Speed: {download_speed_str}\n"
                            f"Estimated time remaining: {remaining_time_str}"
                        )
                    )
                    last_update_time = current_time

    elif d['status'] == 'finished':
        context.application.create_task(progress_message.edit_text("Download finished!"))
    elif d['status'] == 'postprocessing':
        context.application.create_task(progress_message.edit_text("Converting audio..."))

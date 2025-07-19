import os
import re
import uuid
import aiofiles
import aiofiles.os
import aiohttp
import asyncio
import subprocess
from telegram import Update
from telegram.ext import ContextTypes

DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Semaphores to limit concurrent downloads and uploads
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(5) # Limit concurrent downloads
UPLOAD_SEMAPHORE = asyncio.Semaphore(2)  # Limit concurrent uploads to Telegram

async def resolve_url(url):
    """Resolve redirect URLs to their canonical form."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.head(url, allow_redirects=True, timeout=5) as response:
                resolved_url = str(response.url)
                print(f"Resolved URL: {url} -> {resolved_url}")
                return resolved_url
        except Exception as e:
            print(f"Failed to resolve URL {url}: {e}")
            return url


async def get_video_title(url):
    """Get video title using yt-dlp metadata extraction."""
    try:
        cmd = ["yt-dlp", "--print", "%(title)s", url]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            title = stdout.decode().strip()
            print(f"Extracted title: {title}")
            return title
        else:
            print(f"Error getting title for {url}: {stderr.decode().strip()}")
            return None
    except Exception as e:
        print(f"Error getting title for {url}: {e}")
        return None


async def download_with_ytdlp(url, output_path):
    """Download video using yt-dlp and fix with ffmpeg for Telegram compatibility."""
    try:
        # Download with yt-dlp, forcing mp4 container, best video/audio, and applying ffmpeg fix
        cmd = [
            "yt-dlp",
            "-f", "bv*+ba/b",                  # best video + best audio
            "--recode-video", "mp4",           # force mp4 container
            "--postprocessor-args", "ffmpeg:-movflags +faststart", # Apply faststart with ffmpeg
            "--audio-format", "m4a",           # standard audio format
            "--no-playlist",                   # no playlists
            "--max-filesize", "50M",           # filesize limit
            "-o", output_path,
            url
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise Exception(f"yt-dlp failed: {stderr.decode().strip()}")

        print(f"Downloaded and fixed video to {output_path}")

    except Exception as e:
        print(f"Error downloading video {url}: {e}")
        raise


async def _perform_initial_checks(update: Update, command_name: str) -> bool:
    from comm_checker import check_user_approval, command_states  # Delayed import

    if not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("You are not approved to use this feature.")
        return False

    if not command_states.get(command_name, True):
        await update.message.reply_text(f"{command_name.capitalize()} download is disabled.")
        return False
    return True

VIDEO_URL_PATTERNS = [
    # Facebook Watch/Video/Reel links
    r'https?://(?:www\.)?fb\.watch/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?fb\.com/watch/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?fb\.com/watch\?v=\d+/?(?:&.*)?',
    r'https?://(?:www\.)?facebook\.com/watch/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?facebook\.com/watch\?v=\d+/?(?:&.*)?',
    r'https?://(?:www\.)?facebook\.com/reel/\d+/?(?:\?.*)?',
    r'https?://(?:www\.)?facebook\.com/share/v/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?facebook\.com/share/r/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?facebook\.com/[^/]+/videos/\w+/?(?:\?.*)?',
    r'https?://(?:www\.)?facebook\.com/photo\.php\?v=\d+/?(?:&.*)?',
    r'https?://(?:www\.)?facebook\.com/video\.php\?v=\d+/?(?:&.*)?',
    r'https?://(?:www\.)?facebook\.com/[^/]+/posts/\d+/?(?:&.*)?',
    r'https?://(?:www\.)?facebook\.com/story\.php\?story_fbid=\d+&id=\d+/?(?:&.*)?',
    # Instagram Reel/Video/Post links
    r'https?://(?:www\.)?instagram\.com/reel/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagram\.com/p/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagram\.com/tv/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagr\.am/reel/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagr\.am/p/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagr\.am/tv/[\w\-]+/?(?:\?.*)?',
]

VIDEO_URL_REGEX = r'|'.join(VIDEO_URL_PATTERNS)

async def handle_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle detected Facebook or Instagram video/reel links."""
    progress_message = None
    task_id = str(uuid.uuid4())[:4]
    print(f"Starting video task {task_id} for user {update.effective_user.id}")

    try:
        if not await _perform_initial_checks(update, 'reel'):
            return

        # Extract URL from message
        message_text = update.message.text
        print(f"Received message: {message_text}")
        match = re.search(VIDEO_URL_REGEX, message_text, re.IGNORECASE)
        url = match.group(0) if match else None

        if not url:
            print(f"No valid video URL found in message for task {task_id}")
            await update.message.reply_text("❌ No valid video URL found in your message.")
            return

        resolved_url = await resolve_url(url)
        if not resolved_url:
            await update.message.reply_text("❌ Could not resolve the video URL.")
            return

        progress_message = await update.message.reply_text("Processing your request...")

        resolved_url = await resolve_url(url)
        if not resolved_url:
            await progress_message.edit_text("❌ Could not resolve the video URL.")
            return
        await progress_message.edit_text(f"Resolving video URL")

        # Get video title and clean hashtags
        await progress_message.edit_text("Extracting video title...")
        video_title = await get_video_title(resolved_url)
        if video_title:
            video_title = re.sub(r'#\S+', '', video_title).strip()

        caption_text = f"🎬 {video_title}" if video_title else None

        video_file_path = os.path.join(DOWNLOAD_DIR, f"{uuid.uuid4().hex}.mp4")

        try:
            # Check file size from headers before download (optional, may not always work)
            async with aiohttp.ClientSession() as session:
                async with session.head(resolved_url, timeout=5) as head_response:
                    file_size = int(head_response.headers.get('Content-Length', 0))
                    if file_size and file_size > 50 * 1024 * 1024: # Increased to 50MB
                        await progress_message.edit_text(
                            f"❌ Video too large ({file_size / (1024 * 1024):.1f} MB)."
                        )
                        return

            await progress_message.edit_text("Downloading video...")
            async with DOWNLOAD_SEMAPHORE:
                await download_with_ytdlp(resolved_url, video_file_path)

            if not await aiofiles.os.path.exists(video_file_path):
                await progress_message.edit_text("❌ Video file not found after download.")
                return

            await progress_message.edit_text("Sending video...")
            try:
                async with UPLOAD_SEMAPHORE:
                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=video_file_path,
                        caption=caption_text
                    )
                await progress_message.delete()
            except Exception as send_error:
                print(f"Error sending video in task {task_id}: {send_error}")
                await progress_message.edit_text(
                    f"❌ Error sending video: `{str(send_error)}`"
                )
                return

        except Exception as e:
            print(f"Error downloading video in task {task_id}: {e}")
            await progress_message.edit_text(
                f"❌ Error downloading video: `{str(e)}`\nTry sharing the direct video URL or ensure it's public."
            )
            return
        finally:
            if video_file_path and await aiofiles.os.path.exists(video_file_path):
                try:
                    await aiofiles.os.remove(video_file_path)
                    print(f"Cleaned up video file: {video_file_path}")
                except Exception as e:
                    print(f"Error cleaning up video file {video_file_path}: {e}")

    except Exception as e:
        print(f"Critical error in task {task_id}: {e}")
        if progress_message:
            await progress_message.edit_text(f"❌ Critical error: `{str(e)}`")
        else:
            await update.message.reply_text(f"❌ Critical error: `{str(e)}`")
    finally:
        print(f"Completed video task {task_id}")

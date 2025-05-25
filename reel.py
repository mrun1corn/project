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

async def download_with_ytdlp(url, output_path):
    """Download video using yt-dlp."""
    try:
        cmd = [
            "yt-dlp",
            "-f", "bestvideo+bestaudio",
            "--merge-output-format", "mp4",
            "-o", output_path,
            url
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            print(f"Downloaded video to {output_path}")
        else:
            raise Exception(f"yt-dlp failed: {stderr.decode()}")
    except Exception as e:
        print(f"Error downloading video: {e}")
        raise

async def handle_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle detected Facebook or Instagram video/reel links."""
    from comm_checker import check_user_approval, command_states  # Delayed import
    progress_message = None
    task_id = str(uuid.uuid4())[:4]
    print(f"Starting video task {task_id} for user {update.effective_user.id}")

    try:
        if not await check_user_approval(update.effective_user.id):
            await update.message.reply_text("You are not approved to use this feature.", parse_mode=None)
            return

        if not command_states.get('video', True):
            await update.message.reply_text("Video download is disabled.", parse_mode=None)
            return

        # Extract URL from message
        message_text = update.message.text
        print(f"Received message: {message_text}")
        video_patterns = [
            r'https?://(?:www\.)?fb\.watch/[\w\-]+/?(?:\?.*)?',  # fb.watch
            r'https?://(?:www\.)?facebook\.com/reel/\d+/?(?:\?.*)?',  # Reels
            r'https?://(?:www\.)?facebook\.com/share/v/[\w\-]+/?(?:\?.*)?',  # Share/v
            r'https?://(?:www\.)?facebook\.com/share/r/[\w\-]+/?(?:\?.*)?',  # Share/r
            r'https?://(?:www\.)?facebook\.com/[^/]+/videos/\w+/?(?:\?.*)?',  # Videos
            r'https?://(?:www\.)?instagram\.com/reel/[\w\-]+/?(?:\?.*)?'  # Instagram Reels
        ]
        url = None
        for pattern in video_patterns:
            match = re.search(pattern, message_text, re.IGNORECASE)
            if match:
                url = match.group(0)
                print(f"Matched URL: {url} with pattern {pattern}")
                break

        if not url:
            print(f"No valid video URL found in message for task {task_id}")
            return

        # Resolve URL
        resolved_url = await resolve_url(url)
        progress_message = await update.message.reply_text(
            f"Processing video: {resolved_url}",
            parse_mode=None
        )

        DOWNLOAD_DIR = 'downloads'
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        video_file_path = os.path.join(DOWNLOAD_DIR, f"{uuid.uuid4().hex}.mp4")

        try:
            # Check file size (approximate via HEAD request)
            async with aiohttp.ClientSession() as session:
                async with session.head(resolved_url, timeout=5) as head_response:
                    file_size = int(head_response.headers.get('Content-Length', 0))
                    if file_size and file_size > 40 * 1024 * 1024:
                        await progress_message.edit_text(
                            f"Video too large ({file_size/(1024*1024):.1f} MB).",
                            parse_mode=None
                        )
                        return

            await progress_message.edit_text("Downloading video...", parse_mode=None)
            await download_with_ytdlp(resolved_url, video_file_path)

            if not await aiofiles.os.path.exists(video_file_path):
                await progress_message.edit_text("Video file not found after download.", parse_mode=None)
                return

            await progress_message.edit_text("Sending video...", parse_mode=None)
            try:
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=open(video_file_path, 'rb')
                )
                await progress_message.delete()
            except Exception as send_error:
                print(f"Error sending video in task {task_id}: {send_error}")
                await progress_message.edit_text(
                    f"Error sending video: {str(send_error)}",
                    parse_mode=None
                )
                return

        except Exception as e:
            print(f"Error downloading video in task {task_id}: {e}")
            await progress_message.edit_text(
                f"Error downloading video: {str(e)}\nTry sharing the direct video URL (for example, fb.watch or facebook.com/videos) or ensure the video is public.",
                parse_mode=None
            )
            return
        finally:
            if await aiofiles.os.path.exists(video_file_path):
                await aiofiles.os.remove(video_file_path)

    except Exception as e:
        print(f"Critical error in task {task_id}: {e}")
        if progress_message:
            await progress_message.edit_text(f"Critical error: {str(e)}", parse_mode=None)
        else:
            await update.message.reply_text(f"Critical error: {str(e)}", parse_mode=None)
    finally:
        print(f"Completed video task {task_id}")
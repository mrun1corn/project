from __future__ import annotations

import html
import re

import aiohttp
import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes

from src.core.guard import CommandSpec, guard_command
from src.core.media import (
    DOWNLOAD_SEMAPHORE,
    MAX_TELEGRAM_FILE_SIZE,
    UPLOAD_SEMAPHORE,
    cleanup_workspace,
    create_workspace,
    download_media,
    estimate_filesize,
    extract_media_info,
    pick_entry,
    safe_delete_message,
    safe_edit_message,
    send_media_with_retry,
)


async def resolve_url(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        try:
            async with session.head(url, allow_redirects=True, timeout=5) as response:
                return str(response.url)
        except Exception:
            return url


async def _perform_initial_checks(update: Update, command_name: str) -> bool:
    return await guard_command(
        update,
        CommandSpec(
            name=command_name,
            approval_message="⚠️ You are not approved to use this media feature yet.",
            disabled_message=f"⚠️ {command_name.capitalize()} downloads are currently disabled.",
        ),
    )


VIDEO_URL_PATTERNS = [
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
    r'https?://(?:www\.)?facebook\.com/[^/]+/posts/\d+/?(?:\?.*)?',
    r'https?://(?:www\.)?facebook\.com/story\.php\?story_fbid=\d+&id=\d+/?(?:&.*)?',
    r'https?://(?:www\.)?instagram\.com/reel/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagram\.com/p/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagram\.com/tv/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagr\.am/reel/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagr\.am/p/[\w\-]+/?(?:\?.*)?',
    r'https?://(?:www\.)?instagr\.am/tv/[\w\-]+/?(?:\?.*)?',
]

VIDEO_URL_REGEX = r'|'.join(VIDEO_URL_PATTERNS)
REEL_FORMAT_SELECTOR = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"


async def handle_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    progress_message = None
    workspace = None
    completed = False

    try:
        if not await _perform_initial_checks(update, "reel"):
            return

        message_text = update.message.text or ""
        match = re.search(VIDEO_URL_REGEX, message_text, re.IGNORECASE)
        url = match.group(0) if match else None

        if not url:
            await update.message.reply_text("⚠️ I couldn't find a supported video link in that message.")
            return

        progress_message = await update.message.reply_text("<b>Reel Downloader</b>\n🔗 Processing your link...", parse_mode="HTML")
        await safe_edit_message(progress_message, "<b>Reel Downloader</b>\n🧭 Resolving the shared link...")
        resolved_url = await resolve_url(url)
        workspace = create_workspace("reel")

        async with DOWNLOAD_SEMAPHORE:
            await safe_edit_message(progress_message, "<b>Reel Downloader</b>\n🌐 Fetching video details...")
            info = await extract_media_info(resolved_url, format_selector=REEL_FORMAT_SELECTOR)
            entry = pick_entry(info)
            title = re.sub(r'#\S+', '', (entry.get("title") or "Reel Video")).strip() or "Reel Video"

            estimated_size = estimate_filesize(entry)
            if estimated_size and estimated_size > MAX_TELEGRAM_FILE_SIZE:
                await safe_edit_message(
                    progress_message,
                    f"<b>Reel Too Large</b>\nTelegram can only accept up to <code>{MAX_TELEGRAM_FILE_SIZE / (1024 * 1024):.1f} MB</code>.\nDetected size: <code>{estimated_size / (1024 * 1024):.1f} MB</code>.",
                )
                return

            await safe_edit_message(progress_message, f"<b>Reel Downloader</b>\n⬇️ Downloading <code>{html.escape(title)}</code>...")
            media = await download_media(
                entry.get("webpage_url") or resolved_url,
                workspace=workspace,
                format_selector=REEL_FORMAT_SELECTOR,
                title=title,
                merge_output_format="mp4",
            )

        if media.filesize and media.filesize > MAX_TELEGRAM_FILE_SIZE:
            await safe_edit_message(
                progress_message,
                f"<b>Reel Too Large</b>\nThe downloaded file is <code>{media.filesize / (1024 * 1024):.1f} MB</code>, which is above Telegram's limit.",
            )
            return

        await safe_edit_message(progress_message, "<b>Reel Downloader</b>\n📤 Sending the video...")
        async with UPLOAD_SEMAPHORE:
            sent = await send_media_with_retry(
                context,
                chat_id=update.effective_chat.id,
                media=media,
                media_type="video",
                caption=title,
            )
        if not sent:
            await safe_edit_message(progress_message, "<b>Reel Delivery Failed</b>\n⚠️ I couldn't send the video after multiple retries.")
            return

        completed = True
        await safe_delete_message(progress_message)
    except yt_dlp.utils.DownloadError as exc:
        await safe_edit_message(
            progress_message,
            f"<b>Reel Download Failed</b>\n<code>{html.escape(str(exc))}</code>",
        )
    except Exception as exc:
        await safe_edit_message(
            progress_message,
            f"<b>Reel Processing Failed</b>\nMake sure the post is public and try again.\n<code>{html.escape(str(exc))}</code>",
        )
    finally:
        cleanup_workspace(workspace)
        if not completed:
            print(f"Reel handler finished with an error for chat {update.effective_chat.id}")

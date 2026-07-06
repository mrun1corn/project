from __future__ import annotations

import html

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
    sanitize_media_name,
    send_media_with_retry,
)


AUDIO_FORMAT_SELECTOR = "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[ext=opus]/bestaudio"
VIDEO_FORMAT_SELECTOR = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"


async def _perform_initial_checks(update: Update, command_name: str, usage_message: str) -> bool:
    return await guard_command(update, CommandSpec(name=command_name, usage=usage_message), require_args=True)


def _format_file_size(size_in_bytes: int) -> str:
    return f"{size_in_bytes / (1024 * 1024):.1f} MB"


async def _handle_media_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    command_name: str,
    query: str,
    progress_label: str,
    media_type: str,
    format_selector: str,
    merge_output_format: str | None = None,
) -> None:
    progress_message = await update.message.reply_text(
        f"<b>{progress_label.title()} Search</b>\n🔎 Looking for <code>{html.escape(query)}</code>",
        parse_mode="HTML",
    )
    workspace = create_workspace(command_name)
    completed = False

    try:
        async with DOWNLOAD_SEMAPHORE:
            await safe_edit_message(progress_message, f"<b>{progress_label.title()} Search</b>\n🌐 Looking up the best source...")
            info = await extract_media_info(query, format_selector=format_selector, default_search="ytsearch1")
            entry = pick_entry(info)
            title = sanitize_media_name(entry.get("title") or query)

            estimated_size = estimate_filesize(entry)
            if estimated_size and estimated_size > MAX_TELEGRAM_FILE_SIZE:
                await safe_edit_message(
                    progress_message,
                    f"<b>{progress_label.title()} Too Large</b>\nTelegram can only accept up to <code>{_format_file_size(MAX_TELEGRAM_FILE_SIZE)}</code>.\nDetected size: <code>{_format_file_size(estimated_size)}</code>.",
                )
                return

            await safe_edit_message(progress_message, f"<b>{progress_label.title()} Download</b>\n⬇️ Downloading <code>{html.escape(title)}</code>...")
            media = await download_media(
                entry.get("webpage_url") or query,
                workspace=workspace,
                format_selector=format_selector,
                title=title,
                merge_output_format=merge_output_format,
            )

        if media.filesize and media.filesize > MAX_TELEGRAM_FILE_SIZE:
            await safe_edit_message(
                progress_message,
                f"<b>{progress_label.title()} Too Large</b>\nThe finished file is <code>{_format_file_size(media.filesize)}</code>, which exceeds Telegram's upload limit.",
            )
            return

        await safe_edit_message(progress_message, f"<b>{progress_label.title()} Upload</b>\n📤 Sending your file now...")
        async with UPLOAD_SEMAPHORE:
            sent = await send_media_with_retry(
                context,
                chat_id=update.effective_chat.id,
                media=media,
                media_type=media_type,
                caption=media.title if media_type == "video" else None,
            )

        if not sent:
            await safe_edit_message(progress_message, f"<b>{progress_label.title()} Failed</b>\n⚠️ I couldn't send the file after multiple retries.")
            return

        completed = True
        await safe_delete_message(progress_message)
    except yt_dlp.utils.DownloadError as exc:
        await safe_edit_message(
            progress_message,
            f"<b>{progress_label.title()} Download Failed</b>\n<code>{html.escape(str(exc))}</code>",
        )
    except Exception as exc:
        await safe_edit_message(
            progress_message,
            f"<b>{progress_label.title()} Failed</b>\n<code>{html.escape(str(exc))}</code>",
        )
    finally:
        cleanup_workspace(workspace)
        if not completed:
            print(f"{command_name} command finished with an error for chat {update.effective_chat.id}")


async def play_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _perform_initial_checks(update, "music", "🎵 Usage: /music <song name>"):
        return

    query = " ".join(context.args).strip()
    await _handle_media_command(
        update,
        context,
        command_name="music",
        query=query,
        progress_label="audio",
        media_type="audio",
        format_selector=AUDIO_FORMAT_SELECTOR,
    )


async def play_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _perform_initial_checks(update, "video", "🎬 Usage: /video <video name>"):
        return

    query = " ".join(context.args).strip()
    await _handle_media_command(
        update,
        context,
        command_name="video",
        query=query,
        progress_label="video",
        media_type="video",
        format_selector=VIDEO_FORMAT_SELECTOR,
        merge_output_format="mp4",
    )

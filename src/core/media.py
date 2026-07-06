from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp
from telegram import Message
from telegram.error import RetryAfter, TimedOut


DOWNLOAD_ROOT = Path("downloads")
DOWNLOAD_ROOT.mkdir(exist_ok=True)

DOWNLOAD_SEMAPHORE = asyncio.Semaphore(4)
UPLOAD_SEMAPHORE = asyncio.Semaphore(2)
MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024


@dataclass(frozen=True)
class DownloadedMedia:
    path: str
    title: str
    source_url: str
    filesize: int | None = None


def sanitize_media_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]", "_", name).strip()
    return cleaned or "media"


def create_workspace(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=f"{prefix}_", dir=str(DOWNLOAD_ROOT))


def cleanup_workspace(path: str | None) -> None:
    if path and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def pick_entry(info: dict[str, Any]) -> dict[str, Any]:
    if info.get("entries"):
        entries = [entry for entry in info["entries"] if entry]
        if not entries:
            raise ValueError("No search results were found.")
        return entries[0]
    return info


def estimate_filesize(info: dict[str, Any]) -> int | None:
    candidates: list[int] = []

    for key in ("filesize", "filesize_approx"):
        value = info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            candidates.append(int(value))

    for item in info.get("requested_formats") or []:
        for key in ("filesize", "filesize_approx"):
            value = item.get(key)
            if isinstance(value, (int, float)) and value > 0:
                candidates.append(int(value))

    if candidates:
        return sum(candidates)

    duration = info.get("duration")
    tbr = info.get("tbr")
    if isinstance(duration, (int, float)) and isinstance(tbr, (int, float)) and duration > 0 and tbr > 0:
        return int((tbr * 1000 / 8) * duration)

    return None


def ensure_binary_available(binary_name: str) -> None:
    if shutil.which(binary_name):
        return
    raise RuntimeError(f"Required dependency '{binary_name}' is not installed on this host.")


async def extract_media_info(
    source: str,
    *,
    format_selector: str,
    default_search: str | None = None,
) -> dict[str, Any]:
    ydl_opts = {
        "format": format_selector,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    if default_search:
        ydl_opts["default_search"] = default_search

    def _extract() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(source, download=False)

    return await asyncio.to_thread(_extract)


async def download_media(
    source: str,
    *,
    workspace: str,
    format_selector: str,
    title: str,
    merge_output_format: str | None = None,
) -> DownloadedMedia:
    if merge_output_format:
        ensure_binary_available("ffmpeg")

    safe_title = sanitize_media_name(title)
    output_template = os.path.join(workspace, f"{safe_title}.%(ext)s")

    ydl_opts = {
        "format": format_selector,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": output_template,
        "restrictfilenames": False,
    }
    if merge_output_format:
        ydl_opts["merge_output_format"] = merge_output_format

    def _download() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(source, download=True)

    info = await asyncio.to_thread(_download)
    entry = pick_entry(info)

    files = [
        os.path.join(workspace, name)
        for name in os.listdir(workspace)
        if not name.endswith((".part", ".ytdl"))
    ]
    files = [path for path in files if os.path.isfile(path)]
    if not files:
        raise FileNotFoundError("Download completed but no media file was produced.")

    files.sort(key=os.path.getmtime, reverse=True)
    media_path = files[0]
    return DownloadedMedia(
        path=media_path,
        title=entry.get("title") or title,
        source_url=entry.get("webpage_url") or source,
        filesize=os.path.getsize(media_path),
    )


async def send_media_with_retry(
    context,
    *,
    chat_id: int,
    media: DownloadedMedia,
    media_type: str,
    caption: str | None = None,
    max_retries: int = 3,
) -> bool:
    for attempt in range(max_retries):
        try:
            with open(media.path, "rb") as stream:
                if media_type == "audio":
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=stream,
                        title=media.title,
                        caption=caption,
                    )
                elif media_type == "video":
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=stream,
                        caption=caption,
                        supports_streaming=True,
                    )
                else:
                    raise ValueError(f"Unsupported media type: {media_type}")
            return True
        except RetryAfter as exc:
            print(f"Retrying media send after rate limit: {exc.retry_after}s")
            await asyncio.sleep(exc.retry_after)
        except (TimedOut, asyncio.TimeoutError) as exc:
            print(f"Retrying media send after timeout: {exc}")
            await asyncio.sleep(2 ** attempt)
        except Exception as exc:
            print(f"Retrying media send after failure: {exc}")
            await asyncio.sleep(2 ** attempt)
    return False


async def safe_edit_message(message: Message | None, text: str, **kwargs) -> None:
    if not message:
        return
    try:
        kwargs.setdefault("parse_mode", "HTML")
        await message.edit_text(text, **kwargs)
    except Exception:
        pass


async def safe_delete_message(message: Message | None) -> None:
    if not message:
        return
    try:
        await message.delete()
    except Exception:
        pass

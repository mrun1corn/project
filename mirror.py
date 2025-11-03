import asyncio
import html
import os
import shutil
import tempfile
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlparse, quote

import aiohttp
import requests
import qbittorrentapi
import aiofiles
import json
from aiohttp import BasicAuth, ClientSession, ClientTimeout
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from settings import settings
from comm_checker import check_user_approval, check_command_enabled


ALLOWED_TARGETS = {"pixeldrain", "gofile"}
TARGET_LABELS = {"pixeldrain": "PixelDrain", "gofile": "GoFile"}
CANCEL_CALLBACK_PREFIX = "mirror_cancel"
STATUS_EMOJIS = {
    "queued": "🟡",
    "downloading": "⬇️",
    "uploading": "⬆️",
    "compressing": "🗜️",
    "cancelling": "⏹️",
    "cancelled": "🚫",
    "completed": "✅",
    "error": "❌",
}

TARGET_QUEUE: Optional[Deque[str]] = None
TARGET_QUEUE_LOCK = asyncio.Lock()


def ensure_download_dir() -> str:
    path = settings.mirror_download_dir
    try:
        os.makedirs(path, exist_ok=True)
        test_path = os.path.join(path, ".permcheck")
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        return path
    except Exception:
        fallback = os.path.join(tempfile.gettempdir(), "mirror")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _build_target_queue() -> Deque[str]:
    configured = list(settings.upload_targets or ())
    if not configured:
        configured = [settings.upload_target or "pixeldrain"]

    queue: list[str] = []
    for candidate in configured:
        normalized = candidate.lower()
        if normalized not in ALLOWED_TARGETS:
            continue
        if normalized == "pixeldrain" and not settings.pixeldrain_key:
            continue
        queue.append(normalized)

    if not queue:
        if settings.pixeldrain_key:
            queue.append("pixeldrain")
        else:
            queue.append("gofile")
    elif not settings.upload_targets_defined:
        if settings.pixeldrain_key and "pixeldrain" not in queue:
            queue.append("pixeldrain")
        if settings.gofile_token and "gofile" not in queue:
            queue.append("gofile")

    return deque(queue)


async def _effective_target() -> str:
    global TARGET_QUEUE
    async with TARGET_QUEUE_LOCK:
        if TARGET_QUEUE is None or not TARGET_QUEUE:
            TARGET_QUEUE = _build_target_queue()
        target = TARGET_QUEUE[0]
        TARGET_QUEUE.rotate(-1)
        return target


async def _select_target_order() -> Tuple[str, ...]:
    primary = await _effective_target()
    available = list(_build_target_queue())
    ordered = [primary]
    for candidate in available:
        if candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


def _format_size(num: Optional[int]) -> str:
    if not num:
        return "--"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num)
    for unit in units:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def _format_speed(bps: Optional[float]) -> str:
    if not bps:
        return "--"
    return f"{_format_size(int(bps))}/s"


def _format_eta(seconds: Optional[int]) -> str:
    if seconds is None or seconds < 0:
        return "--"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m"
    if minutes:
        return f"{minutes:d}m {sec:02d}s"
    return f"{sec:d}s"


def _progress_bar(percent: float) -> str:
    filled = int(percent // 10)
    return "█" * filled + "░" * (10 - filled)


def _extract_infohash(magnet: str) -> Optional[str]:
    parsed = urlparse(magnet)
    if parsed.scheme != "magnet":
        return None
    params = dict(parse_qsl(parsed.query))
    xt = params.get("xt")
    if xt and xt.lower().startswith("urn:btih:"):
        return xt[9:].upper()
    return None


QB_CLIENT: Optional[qbittorrentapi.Client] = None
QB_LOCK = asyncio.Lock()


async def _get_qb_client() -> qbittorrentapi.Client:
    global QB_CLIENT
    async with QB_LOCK:
        if QB_CLIENT is None:
            QB_CLIENT = qbittorrentapi.Client(
                host=settings.qbittorrent_host,
                port=settings.qbittorrent_port,
                username=settings.qbittorrent_username,
                password=settings.qbittorrent_password,
            )
            try:
                await asyncio.to_thread(QB_CLIENT.auth_log_in)
            except qbittorrentapi.LoginFailed as exc:
                QB_CLIENT = None
                raise RuntimeError(f"Failed to connect to qBittorrent: {exc}")
        return QB_CLIENT


@dataclass
class MirrorTask:
    task_id: str
    user_id: int
    chat_id: int
    status_message_id: int
    application: any
    created_at: float = field(default_factory=time.time)
    name: str = ""
    phase: str = "queued"
    progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    speed: Optional[float] = None
    eta: Optional[int] = None
    upload_link: Optional[str] = None
    error: Optional[str] = None
    local_path: Optional[str] = None
    is_directory: bool = False
    last_update: float = field(default_factory=lambda: 0.0)
    status_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_requested: bool = False
    cancelled: bool = False
    cancel_reason: Optional[str] = None
    finished: bool = False
    current_target: Optional[str] = None

    async def update_message(self, force: bool = False) -> None:
        async with self.status_lock:
            now = time.time()
            if not force and now - self.last_update < settings.mirror_status_interval:
                return
            self.last_update = now

            emoji = STATUS_EMOJIS.get(self.phase, "ℹ️")
            short_id = self.task_id[:8] if self.task_id else "--"
            lines = [f"{emoji} <b>Status:</b> {self.phase.title()}"]
            if self.name:
                lines.append(f"<b>Name:</b> <code>{html.escape(self.name)}</code>")
            if self.task_id:
                lines.append(f"<b>Task ID:</b> <code>{self.task_id}</code>")
            duration = now - self.created_at
            lines.append(f"<b>Elapsed:</b> {_format_eta(int(duration))}")

            if self.phase in {"downloading", "uploading", "compressing"}:
                if self.total_bytes:
                    percent = min(max(self.progress, 0.0), 100.0)
                    lines.append(
                        f"<b>Progress:</b> {_progress_bar(percent)} {percent:.1f}%"
                    )
                    lines.append(
                        f"<b>Transferred:</b> {_format_size(self.downloaded_bytes)} / {_format_size(self.total_bytes)}"
                    )
                else:
                    lines.append(f"<b>Transferred:</b> {_format_size(self.downloaded_bytes)}")
                if self.current_target and self.phase in {"uploading", "compressing"}:
                    target_label = TARGET_LABELS.get(self.current_target, self.current_target)
                    lines.append(f"<b>Target:</b> {html.escape(target_label)}")
                lines.append(f"<b>Speed:</b> {_format_speed(self.speed)}")
                if self.phase == "downloading" and self.total_bytes:
                    remaining = (
                        (self.total_bytes - self.downloaded_bytes)
                        if self.total_bytes else None
                    )
                    eta = int(remaining / max(self.speed or 1, 1)) if remaining else None
                    lines.append(f"<b>ETA:</b> {_format_eta(eta)}")
                elif self.phase == "uploading":
                    lines.append("<i>Uploading to mirror target…</i>")
            elif self.phase == "completed" and self.upload_link:
                lines.append("<b>Result:</b> Ready")
            elif self.phase == "cancelled":
                reason = self.cancel_reason or self.error
                if reason:
                    lines.append(f"<b>Cancelled:</b> {html.escape(reason)}")
            elif self.phase == "cancelling":
                if self.cancel_reason:
                    lines.append(f"<i>{html.escape(self.cancel_reason)}</i>")
                else:
                    lines.append("<i>Waiting for background tasks to stop…</i>")
            elif self.phase == "error" and self.error:
                lines.append(f"<b>Error:</b> {html.escape(self.error)}")

            if (
                not self.finished
                and not self.cancel_requested
                and self.phase not in {"completed", "cancelled", "cancelling", "error"}
                and self.task_id
            ):
                cancel_cmd = f"/cancel {self.task_id}"
                lines.append(
                    f"<i>Tap ⛔ {short_id} below or send</i> <code>{cancel_cmd}</code>"
                    " <i>to stop this task.</i>"
                )

            text = "\n".join(lines)

            reply_markup = None
            if self.phase == "completed" and self.upload_link:
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Open Link", url=self.upload_link)]]
                )
            elif (
                not self.finished
                and not self.cancel_requested
                and self.phase not in {"cancelled", "cancelling", "error"}
            ):
                button_text = f"⛔ {short_id}"
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(button_text, callback_data=f"{CANCEL_CALLBACK_PREFIX}:{self.task_id}")]]
                )

            try:
                await self.application.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.status_message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
            except TelegramError:
                try:
                    message = await self.application.bot.send_message(
                        chat_id=self.chat_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                    )
                    self.status_message_id = message.message_id
                except TelegramError:
                    pass


ACTIVE_TASKS: Dict[str, MirrorTask] = {}
USER_TASKS: Dict[int, set[str]] = {}


class MirrorCancelled(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _cancel_reason(task: MirrorTask) -> str:
    return task.cancel_reason or "Cancelled"


def _ensure_not_cancelled(task: MirrorTask) -> None:
    if task.cancel_requested:
        raise MirrorCancelled(_cancel_reason(task))


def _track_task(task: MirrorTask) -> None:
    ACTIVE_TASKS[task.task_id] = task
    USER_TASKS.setdefault(task.user_id, set()).add(task.task_id)


def _untrack_task(task: MirrorTask) -> None:
    ACTIVE_TASKS.pop(task.task_id, None)
    user_tasks = USER_TASKS.get(task.user_id)
    if user_tasks is not None:
        user_tasks.discard(task.task_id)
        if not user_tasks:
            USER_TASKS.pop(task.user_id, None)


async def _request_task_cancel(task: MirrorTask, reason: str) -> bool:
    if task.finished or task.cancelled or task.cancel_requested:
        return False
    task.cancel_requested = True
    task.cancel_reason = reason
    task.phase = "cancelling"
    task.error = reason
    task.cancel_event.set()
    await task.update_message(force=True)
    return True


def _get_task_by_status_message(message_id: int) -> Optional[MirrorTask]:
    for task in ACTIVE_TASKS.values():
        if task.status_message_id == message_id:
            return task
    return None


def _get_user_active_tasks(user_id: int) -> list[MirrorTask]:
    task_ids = USER_TASKS.get(user_id, set())
    return [ACTIVE_TASKS[task_id] for task_id in task_ids if task_id in ACTIVE_TASKS]


async def mirror_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user
    if not user:
        return

    if not await check_user_approval(user.id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return

    if not await check_command_enabled("mirror"):
        await update.message.reply_text("❌ The mirror command is currently disabled.")
        return

    target_message = update.message.reply_to_message
    args = context.args

    source = None
    source_name = None

    if target_message:
        if target_message.document:
            doc_name = target_message.document.file_name or ""
            if doc_name.lower().endswith(".torrent") or (
                target_message.document.mime_type or ""
            ).endswith("application/x-bittorrent"):
                source = ("telegram_torrent", target_message.document)
                source_name = doc_name
            else:
                source = ("telegram", target_message.document)
                source_name = doc_name
        elif target_message.video:
            source = ("telegram", target_message.video)
            source_name = target_message.video.file_name or "video.mp4"
        elif target_message.audio:
            source = ("telegram", target_message.audio)
            source_name = target_message.audio.file_name or "audio"
        elif target_message.photo:
            source = ("telegram", target_message.photo[-1])
            source_name = "photo.jpg"
        elif text := (target_message.text or target_message.caption):
            source = ("text", text.strip())
    elif args:
        source = ("text", args[0].strip())

    if source is None:
        await update.message.reply_text(
            "Usage: reply to a file/link/magnet with /mirror, or provide a URL."
        )
        return

    status = await update.message.reply_text("🟡 Task queued…")

    task_id = uuid.uuid4().hex
    task = MirrorTask(
        task_id=task_id,
        user_id=user.id,
        chat_id=update.effective_chat.id,
        status_message_id=status.message_id,
        application=context.application,
        name=source_name or task_id,
    )
    _track_task(task)
    await task.update_message(force=True)

    context.application.create_task(
        _run_mirror_task(task, update, context, source)
    )


async def _run_mirror_task(
    task: MirrorTask,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    source,
) -> None:
    download_root = ensure_download_dir()
    task_dir = os.path.join(download_root, task.task_id)
    os.makedirs(task_dir, exist_ok=True)

    local_path = None
    is_dir = False
    name = task.name

    try:
        print(f"[MIRROR] Task {task.task_id} started. Download dir: {task_dir}")
        _ensure_not_cancelled(task)
        src_type, payload = source
        if src_type == "telegram":
            local_path, name = await _download_from_telegram(task, context, payload, task_dir)
        elif src_type == "text":
            text = payload
            if text.startswith("magnet:?"):
                print(f"[MIRROR] Task {task.task_id} detected magnet link")
                local_path, is_dir, name = await _download_torrent(task, text, task_dir)
            elif text.lower().endswith(".torrent"):
                print(f"[MIRROR] Task {task.task_id} detected torrent URL")
                local_path, is_dir, name = await _download_torrent_from_url(task, text, task_dir)
            else:
                print(f"[MIRROR] Task {task.task_id} downloading direct URL")
                local_path, name = await _download_from_url(task, text, task_dir)
        elif src_type == "telegram_torrent":
            print(f"[MIRROR] Task {task.task_id} downloading torrent file from Telegram")
            torrent_path, torrent_name = await _download_from_telegram(
                task, context, payload, task_dir
            )
            local_path, is_dir, name = await _download_torrent_from_file(
                task, torrent_path, task_dir, torrent_name
            )
        else:
            raise ValueError("Unsupported source")

        task.local_path = local_path
        task.is_directory = is_dir or os.path.isdir(local_path)
        task.name = name or os.path.basename(local_path)
        _ensure_not_cancelled(task)
        task.phase = "uploading"
        print(f"[MIRROR] Task {task.task_id} download complete. Path: {local_path}")
        await task.update_message(force=True)

        link = await _upload_to_target(task, local_path)
        print(f"[MIRROR] Task {task.task_id} upload finished. Link: {link}")
        task.upload_link = link
        task.phase = "completed"
        task.progress = 100.0
        task.speed = None
        await task.update_message(force=True)
    except MirrorCancelled as exc:
        task.cancelled = True
        task.phase = "cancelled"
        task.error = exc.reason
        task.speed = None
        task.upload_link = None
        print(f"[MIRROR] Task {task.task_id} cancelled: {exc.reason}")
        await task.update_message(force=True)

    except Exception as exc:
        task.phase = "error"
        task.error = str(exc)
        task.speed = None
        print(f"[MIRROR] Task {task.task_id} failed: {exc}")
        await task.update_message(force=True)
    finally:
        task.finished = True
        task.cancel_event.set()
        _untrack_task(task)
        try:
            if os.path.isdir(task_dir):
                print(f"[MIRROR] Task {task.task_id} cleaning up {task_dir}")
                shutil.rmtree(task_dir, ignore_errors=True)
        except Exception:
            pass


async def _download_from_telegram(task: MirrorTask, context: ContextTypes.DEFAULT_TYPE, file, task_dir: str) -> Tuple[str, str]:
    file_obj = await file.get_file()
    download_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{file_obj.file_path}"
    filename = file.file_name if getattr(file, "file_name", None) else file_obj.file_unique_id
    if getattr(file, "mime_type", "") and "." not in filename:
        if file.mime_type == "video/mp4":
            filename += ".mp4"
        elif file.mime_type == "audio/mpeg":
            filename += ".mp3"
    task.phase = "downloading"
    task.total_bytes = getattr(file, "file_size", None)
    await task.update_message(force=True)
    _ensure_not_cancelled(task)
    downloaded_name, full_path = await _download_http_stream(
        task,
        download_url,
        task_dir,
        filename_hint=filename,
        total_size=task.total_bytes,
    )
    final_name = downloaded_name or filename
    return full_path, final_name


async def _download_from_url(task: MirrorTask, url: str, task_dir: str) -> Tuple[str, str]:
    task.phase = "downloading"
    await task.update_message(force=True)
    _ensure_not_cancelled(task)
    filename, path = await _download_http_stream(task, url, task_dir)
    return path, filename


async def _download_http_stream(
    task: MirrorTask,
    url: str,
    dest_dir: str,
    filename_hint: Optional[str] = None,
    total_size: Optional[int] = None,
) -> Tuple[str, str]:
    os.makedirs(dest_dir, exist_ok=True)
    print(f"[MIRROR] Task {task.task_id} starting HTTP download {url}")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=1200) as response:
            print(f"[MIRROR] Task {task.task_id} response status {response.status}")
            response.raise_for_status()
            if total_size is None:
                total_header = response.headers.get("Content-Length")
                if total_header and total_header.isdigit():
                    total_size = int(total_header)
            filename = filename_hint or _filename_from_response(url, response)
            dest_path = os.path.join(dest_dir, filename)

            task.total_bytes = total_size
            task.downloaded_bytes = 0
            start = time.time()
            chunk_count = 0

            print(f"[MIRROR] Task {task.task_id} writing to {dest_path}")
            with open(dest_path, "wb") as f:
                async for chunk in response.content.iter_chunked(1024 * 512):
                    _ensure_not_cancelled(task)
                    f.write(chunk)
                    task.downloaded_bytes += len(chunk)
                    chunk_count += 1
                    elapsed = time.time() - start
                    if elapsed > 0:
                        task.speed = task.downloaded_bytes / elapsed
                    if total_size:
                        task.progress = min(99.0, task.downloaded_bytes / total_size * 100)
                    if chunk_count % 5 == 0:
                        await task.update_message()

            task.progress = 100.0
            _ensure_not_cancelled(task)
            await task.update_message(force=True)
            print(f"[MIRROR] Task {task.task_id} HTTP download completed")
            return filename, dest_path


async def _download_torrent(task: MirrorTask, magnet: str, task_dir: str) -> Tuple[str, bool, str]:
    client = await _get_qb_client()
    infohash = _extract_infohash(magnet)
    save_path = task_dir
    _ensure_not_cancelled(task)
    await asyncio.to_thread(
        client.torrents_add,
        urls=magnet,
        save_path=save_path,
        category=settings.qbittorrent_category or None,
        is_sequential_download=True,
        skip_checking=True,
    )
    _ensure_not_cancelled(task)
    return await _monitor_torrent(task, client, infohash, save_path)


async def _download_torrent_from_url(task: MirrorTask, url: str, task_dir: str) -> Tuple[str, bool, str]:
    client = await _get_qb_client()
    _ensure_not_cancelled(task)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=1200) as response:
            response.raise_for_status()
            filename_hint = _filename_from_response(url, response)
            torrent_data = await response.read()
    save_path = task_dir
    await asyncio.to_thread(
        client.torrents_add,
        torrent_files=torrent_data,
        save_path=save_path,
        category=settings.qbittorrent_category or None,
        is_sequential_download=True,
        skip_checking=True,
    )
    _ensure_not_cancelled(task)
    # After adding, fetch newest torrent hash
    expected_name = os.path.splitext(filename_hint)[0] if filename_hint else None
    return await _monitor_torrent(task, client, None, save_path, expected_name=expected_name)


async def _download_torrent_from_file(
    task: MirrorTask,
    file_path: str,
    task_dir: str,
    original_name: Optional[str],
) -> Tuple[str, bool, str]:
    client = await _get_qb_client()
    _ensure_not_cancelled(task)
    with open(file_path, "rb") as f:
        torrent_data = f.read()
    try:
        os.remove(file_path)
    except OSError:
        pass
    await asyncio.to_thread(
        client.torrents_add,
        torrent_files=torrent_data,
        save_path=task_dir,
        category=settings.qbittorrent_category or None,
        is_sequential_download=True,
        skip_checking=True,
    )
    _ensure_not_cancelled(task)
    expected_name = None
    if original_name:
        expected_name = os.path.splitext(original_name)[0]
    return await _monitor_torrent(task, client, None, task_dir, expected_name=expected_name)


async def _monitor_torrent(
    task: MirrorTask,
    client: qbittorrentapi.Client,
    infohash: Optional[str],
    save_path: str,
    expected_name: Optional[str] = None,
) -> Tuple[str, bool, str]:
    task.phase = "downloading"
    await task.update_message(force=True)
    _ensure_not_cancelled(task)

    torrent = None
    for _ in range(60):
        _ensure_not_cancelled(task)
        torrents = await asyncio.to_thread(client.torrents_info)
        if infohash:
            torrents = [t for t in torrents if t.hash == infohash]
        if expected_name:
            torrents = [t for t in torrents if t.name == expected_name]
        if save_path:
            torrents = [t for t in torrents if t.save_path == save_path]
        if torrents:
            torrent = max(torrents, key=lambda t: t.added_on)
            break
        await asyncio.sleep(1)

    if torrent is None:
        raise RuntimeError("Unable to start torrent download")

    task.name = torrent.name or task.name
    while True:
        if task.cancel_requested:
            await asyncio.to_thread(client.torrents_pause, torrent_hashes=torrent.hash)
            await asyncio.to_thread(client.torrents_delete, torrent_hashes=torrent.hash, delete_files=True)
            raise MirrorCancelled(_cancel_reason(task))
        await task.update_message()
        task.total_bytes = torrent.total_size or task.total_bytes
        task.downloaded_bytes = int((torrent.total_size or 0) * torrent.progress)
        task.progress = float(torrent.progress * 100)
        task.speed = torrent.dlspeed
        if torrent.eta >= 0:
            task.eta = torrent.eta
        state = torrent.state_enum
        if state.is_complete or state == qbittorrentapi.TorrentStates.SEEDING:
            break
        await asyncio.sleep(settings.mirror_status_interval)
        info_list = await asyncio.to_thread(client.torrents_info, torrent_hashes=torrent.hash)
        if not info_list:
            break
        torrent = info_list[0]

    await asyncio.to_thread(client.torrents_pause, torrent_hashes=torrent.hash)
    await asyncio.to_thread(client.torrents_delete, torrent_hashes=torrent.hash, delete_files=False)

    path = os.path.join(torrent.save_path, torrent.name)
    task.progress = 100.0
    await task.update_message(force=True)
    return path, os.path.isdir(path), torrent.name


def _filename_from_response(url: str, response) -> str:
    disposition = response.headers.get("Content-Disposition") or ""
    if "filename=" in disposition:
        filename = disposition.split("filename=")[-1].strip('"')
        if filename:
            return filename
    parsed = urlparse(url)
    if parsed.path:
        basename = os.path.basename(parsed.path)
        if basename:
            return basename
    return f"download_{uuid.uuid4().hex}"


async def _upload_to_target(task: MirrorTask, path: str) -> str:
    targets = await _select_target_order()
    errors: list[str] = []
    upload_path = path
    cleanup_path = None
    _ensure_not_cancelled(task)

    if os.path.isdir(path):
        task.phase = "compressing"
        task.speed = None
        await task.update_message(force=True)
        archive_base = os.path.join(os.path.dirname(path), f"{os.path.basename(path)}")
        upload_path = await asyncio.to_thread(shutil.make_archive, archive_base, "zip", path)
        cleanup_path = upload_path
        _ensure_not_cancelled(task)
    try:
        for target in targets:
            _ensure_not_cancelled(task)
            task.current_target = target
            task.phase = "uploading"
            task.speed = None
            task.progress = 0.0
            task.downloaded_bytes = 0
            try:
                task.total_bytes = os.path.getsize(upload_path)
            except OSError:
                pass
            await task.update_message(force=True)
            print(f"[MIRROR] Task {task.task_id} preparing upload file: {upload_path} (target={target})")

            try:
                _ensure_not_cancelled(task)
                if target == "gofile":
                    _ensure_not_cancelled(task)
                    link = await asyncio.to_thread(_upload_to_gofile, upload_path, os.path.basename(upload_path))
                    task.downloaded_bytes = task.total_bytes or task.downloaded_bytes
                    task.speed = None
                    await task.update_message(force=True)
                else:
                    link = await _upload_to_pixeldrain_async(task, upload_path)
            except MirrorCancelled:
                raise
            except Exception as exc:
                error_message = f"{target}: {exc}"
                errors.append(error_message)
                print(f"[MIRROR] Task {task.task_id} upload failed via {target}: {exc}")
                continue
            if cleanup_path and os.path.exists(cleanup_path):
                os.remove(cleanup_path)
            return link
    finally:
        if cleanup_path and os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
            except OSError:
                pass

    detail = "; ".join(errors) if errors else "No upload targets available"
    raise RuntimeError(f"All upload targets failed: {detail}")


async def _upload_to_pixeldrain_async(task: MirrorTask, filepath: str) -> str:
    _ensure_not_cancelled(task)
    filename = os.path.basename(filepath)
    total_size = os.path.getsize(filepath)
    task.total_bytes = total_size
    task.downloaded_bytes = 0
    start = time.time()

    async def file_generator():
        chunk_size = 1024 * 512
        async with aiofiles.open(filepath, "rb") as f:
            while True:
                if task.cancel_requested:
                    raise MirrorCancelled(_cancel_reason(task))
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                task.downloaded_bytes += len(chunk)
                if task.total_bytes:
                    task.progress = min(99.0, task.downloaded_bytes / task.total_bytes * 100)
                elapsed = time.time() - start
                if elapsed > 0:
                    task.speed = task.downloaded_bytes / elapsed
                await task.update_message()
                _ensure_not_cancelled(task)
                yield chunk

    auth = BasicAuth("", settings.pixeldrain_key) if settings.pixeldrain_key else None
    headers = {"Content-Type": "application/octet-stream"}
    upload_url = f"https://pixeldrain.com/api/file/{quote(filename)}"
    timeout = ClientTimeout(total=3600)

    async with ClientSession(timeout=timeout) as session:
        async with session.put(upload_url, data=file_generator(), auth=auth, headers=headers) as resp:
            text = await resp.text()
            if resp.status not in (200, 201):
                raise ValueError(f"PixelDrain upload failed ({resp.status}): {text}")
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError(f"PixelDrain returned unexpected response: {text}")
    file_id = payload.get("id")
    if not file_id:
        raise ValueError("Invalid response from PixelDrain")

    task.downloaded_bytes = task.total_bytes
    task.progress = 100.0
    task.speed = None
    await task.update_message(force=True)
    return f"https://pixeldrain.com/u/{file_id}"


def _upload_to_gofile(filepath: str, filename: str) -> str:
    if not settings.gofile_token:
        raise ValueError("GoFile token not configured")

    endpoints = settings.gofile_upload_endpoints or ("https://upload.gofile.io/uploadfile",)
    errors: list[str] = []
    folder_id = settings.gofile_folder_id.strip()

    for endpoint in endpoints:
        headers = {"Authorization": f"Bearer {settings.gofile_token}"}
        data = {}
        if folder_id:
            data["folderId"] = folder_id

        with open(filepath, "rb") as f:
            files = {"file": (filename, f)}
            try:
                response = requests.post(
                    endpoint,
                    files=files,
                    data=data or None,
                    headers=headers,
                    timeout=1200,
                )
            except requests.RequestException as exc:
                error_message = f"request error: {exc}"
                errors.append(f"{endpoint}: {error_message}")
                print(f"[MIRROR] GoFile request error via {endpoint}: {exc}")
                continue

        if response.status_code >= 500:
            errors.append(f"{endpoint}: {response.status_code} {response.text}")
            print(f"[MIRROR] GoFile server error via {endpoint}: {response.status_code} {response.text}")
            continue

        if response.status_code == 401:
            raise ValueError("GoFile authentication failed (401). Check API token.")

        try:
            json_payload = response.json()
        except ValueError as exc:
            errors.append(f"{endpoint}: non-JSON response {response.text}")
            print(f"[MIRROR] GoFile non-JSON response via {endpoint}: {response.text}")
            continue

        status = (json_payload.get("status") or "").lower()
        if status and status != "ok":
            message = json_payload.get("message") or json_payload.get("error") or response.text
            errors.append(f"{endpoint}: {status} {message}")
            print(f"[MIRROR] GoFile API error via {endpoint}: {status} {message}")
            continue

        payload = json_payload.get("data") or {}
        link = payload.get("downloadPage") or payload.get("directLink")
        if link:
            return link

        errors.append(f"{endpoint}: missing link in response {json_payload}")
        print(f"[MIRROR] GoFile missing link via {endpoint}: {json_payload}")

    raise ValueError("GoFile upload failed: " + "; ".join(errors))


async def cancel_mirror_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user
    if not user:
        return

    task: Optional[MirrorTask] = None
    reason = None

    args = context.args
    if args:
        candidate = args[0].strip()
        if candidate:
            task = ACTIVE_TASKS.get(candidate)
            if task is None:
                matches = [t for tid, t in ACTIVE_TASKS.items() if tid.startswith(candidate)]
                if len(matches) == 1:
                    task = matches[0]
                elif len(matches) > 1:
                    await update.message.reply_text(
                        "Multiple tasks match that ID. Please provide the full task ID."
                    )
                    return
        if task is None:
            await update.message.reply_text("No active mirror task found with that ID.")
            return
    elif update.message.reply_to_message:
        task = _get_task_by_status_message(update.message.reply_to_message.message_id)
        if task is None:
            await update.message.reply_text("That message is not an active mirror status update.")
            return
    else:
        user_tasks = _get_user_active_tasks(user.id)
        if not user_tasks:
            await update.message.reply_text("You have no active mirror tasks.")
            return
        lines = ["<b>Your active mirror tasks:</b>"]
        for t in user_tasks:
            status = t.phase.title()
            display_name = html.escape(t.name or t.task_id)
            lines.append(f"- <code>{t.task_id}</code> — {status} ({display_name})")
        lines.append("Reply to a status message or use <code>/cancel &lt;task_id&gt;</code> to stop one.")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    if task.finished:
        await update.message.reply_text("That task has already finished.")
        return

    if user.id not in {task.user_id, settings.admin_chat_id}:
        await update.message.reply_text("You can only cancel your own mirror tasks.")
        return

    display_name = (user.full_name or "").strip() or str(user.id)
    reason = f"Cancelled by {display_name}"

    if task.cancel_requested:
        await update.message.reply_text("Cancellation is already in progress for this task.")
        return

    cancelled = await _request_task_cancel(task, reason)
    if cancelled:
        await update.message.reply_text(
            f"Cancellation requested for <code>{task.task_id}</code>.", parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text("Unable to cancel that task (it may have already completed).")


async def mirror_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    if not data.startswith(f"{CANCEL_CALLBACK_PREFIX}:"):
        await query.answer()
        return
    task_id = data.split(":", maxsplit=1)[1]
    task = ACTIVE_TASKS.get(task_id)
    if task is None:
        await query.answer("Task already finished.", show_alert=False)
        return

    user = query.from_user
    if not user:
        return

    if user.id not in {task.user_id, settings.admin_chat_id}:
        await query.answer("You can only cancel your own mirror tasks.", show_alert=True)
        return

    if task.cancel_requested:
        await query.answer("Cancellation already requested.", show_alert=False)
        return

    display_name = (user.full_name or "").strip() or str(user.id)
    reason = f"Cancelled by {display_name}"
    await _request_task_cancel(task, reason)
    await query.answer("Stopping task…", show_alert=False)


def register_mirror_handlers(application) -> None:
    application.add_handler(CommandHandler("mirror", mirror_command))
    application.add_handler(CommandHandler("cancel", cancel_mirror_command))
    application.add_handler(
        CallbackQueryHandler(
            mirror_cancel_callback,
            pattern=rf"^{CANCEL_CALLBACK_PREFIX}:.+",
        )
    )

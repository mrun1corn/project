import asyncio
import html
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from src.core.config import settings
from .constants import (
    CANCEL_CALLBACK_PREFIX,
    STATUS_EMOJIS,
    TARGET_LABELS,
)


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


def _progress_bar(percent: float) -> str:
    percent = min(max(percent, 0.0), 100.0)
    filled = min(int(percent // 6.66), 15)
    return "▰" * filled + "▱" * (15 - filled)


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

            short_id = self.task_id[:8] if self.task_id else ""
            emoji = STATUS_EMOJIS.get(self.phase, "ℹ️")
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
                    lines.append("<i>Uploading to the mirror target...</i>")
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
                    lines.append("<i>Waiting for background tasks to stop...</i>")
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

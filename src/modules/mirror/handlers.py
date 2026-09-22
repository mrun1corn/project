import html
import os
import shutil
import uuid
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from src.core.config import settings
from src.core.security import check_command_enabled, check_user_approval
from .constants import (
    ALLOWED_TARGETS,
    CANCEL_CALLBACK_PREFIX,
    STATUS_EMOJIS,
    TARGET_LABELS,
)
from .downloaders import (
    QB_CLIENT,
    QB_LOCK,
    _download_from_telegram,
    _download_from_url,
    _download_http_stream,
    _download_torrent,
    _download_torrent_from_file,
    _download_torrent_from_url,
    _extract_infohash,
    _filename_from_response,
    _get_qb_client,
    _monitor_torrent,
    ensure_download_dir,
)
from .task import (
    ACTIVE_TASKS,
    USER_TASKS,
    MirrorCancelled,
    MirrorTask,
    _cancel_reason,
    _ensure_not_cancelled,
    _format_eta,
    _format_size,
    _format_speed,
    _get_task_by_status_message,
    _get_user_active_tasks,
    _progress_bar,
    _request_task_cancel,
    _track_task,
    _untrack_task,
)
from .uploaders import (
    _CACHED_CF_ACCOUNT_ID,
    _CACHED_CF_PUBLIC_URL,
    _CF_CACHE_LOCK,
    TARGET_QUEUE,
    TARGET_QUEUE_LOCK,
    _build_target_queue,
    _effective_target,
    _get_cloudflare_account_id,
    _get_cloudflare_public_url,
    _select_target_order,
    _upload_to_cloudflare_async,
    _upload_to_gofile,
    _upload_to_gofile_async,
    _upload_to_pixeldrain_async,
    _upload_to_target,
)


async def mirror_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user
    if not user:
        return

    if not await check_user_approval(user.id):
        await update.message.reply_text("⚠️ You are not approved to use the mirror feature yet.")
        return

    if not await check_command_enabled("mirror"):
        await update.message.reply_text("⚠️ Mirror is currently disabled.")
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
            "<b>Mirror Usage</b>\nReply to a file, link, or magnet with <code>/mirror</code>, or send <code>/mirror &lt;url&gt;</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    status = await update.message.reply_text("<b>Mirror Queue</b>\n🟡 Task queued and waiting to start.", parse_mode=ParseMode.HTML)

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


async def cancel_mirror_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user
    if not user:
        return

    task: Optional[MirrorTask] = None
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
                        "⚠️ Multiple tasks match that ID. Please send the full task ID."
                    )
                    return
        if task is None:
            await update.message.reply_text("⚠️ No active mirror task was found with that ID.")
            return
    elif update.message.reply_to_message:
        task = _get_task_by_status_message(update.message.reply_to_message.message_id)
        if task is None:
            await update.message.reply_text("⚠️ That message is not an active mirror status update.")
            return
    else:
        user_tasks = _get_user_active_tasks(user.id)
        if not user_tasks:
            await update.message.reply_text("ℹ️ You have no active mirror tasks.")
            return
        lines = ["<b>Your Active Mirror Tasks</b>"]
        for t in user_tasks:
            status = t.phase.title()
            display_name = html.escape(t.name or t.task_id)
            lines.append(f"• <code>{t.task_id}</code> - {status} ({display_name})")
        lines.append("Reply to a status message or use <code>/cancel &lt;task_id&gt;</code> to stop one.")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    if task.finished:
        await update.message.reply_text("ℹ️ That mirror task has already finished.")
        return

    if user.id not in {task.user_id, settings.admin_chat_id}:
        await update.message.reply_text("🔒 You can only cancel your own mirror tasks.")
        return

    display_name = (user.full_name or "").strip() or str(user.id)
    reason = f"Cancelled by {display_name}"

    if task.cancel_requested:
        await update.message.reply_text("⏳ Cancellation is already in progress for this task.")
        return

    cancelled = await _request_task_cancel(task, reason)
    if cancelled:
        await update.message.reply_text(
            f"<b>Cancellation Requested</b>\n⏹️ Stopping task <code>{task.task_id}</code>.", parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text("⚠️ Unable to cancel that task. It may have already finished.")


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
        await query.answer("You can only cancel your own tasks.", show_alert=True)
        return

    if task.cancel_requested:
        await query.answer("Cancellation already requested.", show_alert=False)
        return

    display_name = (user.full_name or "").strip() or str(user.id)
    reason = f"Cancelled by {display_name}"
    await _request_task_cancel(task, reason)
    await query.answer("Stopping task...", show_alert=False)


def register_mirror_handlers(application) -> None:
    application.add_handler(CommandHandler("mirror", mirror_command))
    application.add_handler(CommandHandler("cancel", cancel_mirror_command))
    application.add_handler(
        CallbackQueryHandler(
            mirror_cancel_callback,
            pattern=rf"^{CANCEL_CALLBACK_PREFIX}:.+",
        )
    )

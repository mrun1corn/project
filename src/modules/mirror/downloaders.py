import asyncio
import os
import tempfile
import time
import uuid
from typing import Optional, Tuple
from urllib.parse import parse_qsl, urlparse

import aiohttp
import qbittorrentapi
from telegram.ext import ContextTypes

from src.core.config import settings
from .task import (
    MirrorCancelled,
    MirrorTask,
    _cancel_reason,
    _ensure_not_cancelled,
)

QB_CLIENT: Optional[qbittorrentapi.Client] = None
QB_LOCK = asyncio.Lock()


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


def _extract_infohash(magnet: str) -> Optional[str]:
    parsed = urlparse(magnet)
    if parsed.scheme != "magnet":
        return None
    params = dict(parse_qsl(parsed.query))
    xt = params.get("xt")
    if xt and xt.lower().startswith("urn:btih:"):
        return xt[9:].upper()
    return None


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

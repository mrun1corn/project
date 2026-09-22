import asyncio
from collections import deque
import json
import mimetypes
import os
import shutil
import time
from typing import Deque, Optional, Tuple
from urllib.parse import quote

import aiofiles
import aiohttp
import requests
from aiohttp import BasicAuth, ClientSession, ClientTimeout

from src.core.config import settings
from .constants import ALLOWED_TARGETS, TARGET_LABELS
from .task import (
    MirrorCancelled,
    MirrorTask,
    _cancel_reason,
    _ensure_not_cancelled,
)

_CACHED_CF_ACCOUNT_ID: Optional[str] = None
_CACHED_CF_PUBLIC_URL: Optional[str] = None
_CF_CACHE_LOCK = asyncio.Lock()

TARGET_QUEUE: Optional[Deque[str]] = None
TARGET_QUEUE_LOCK = asyncio.Lock()


async def _get_cloudflare_account_id() -> str:
    global _CACHED_CF_ACCOUNT_ID
    if settings.cloudflare_account_id:
        return settings.cloudflare_account_id
    async with _CF_CACHE_LOCK:
        if _CACHED_CF_ACCOUNT_ID:
            return _CACHED_CF_ACCOUNT_ID
        token = settings.cloudflare_api_token
        if not token:
            raise ValueError("Cloudflare API token not configured")
        headers = {"Authorization": f"Bearer {token}"}
        async with ClientSession(timeout=ClientTimeout(total=15)) as session:
            async with session.get("https://api.cloudflare.com/client/v4/accounts", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    accounts = data.get("result", [])
                    if accounts and "id" in accounts[0]:
                        _CACHED_CF_ACCOUNT_ID = accounts[0]["id"]
                        return _CACHED_CF_ACCOUNT_ID
        raise ValueError("Could not determine Cloudflare Account ID. Please set CLOUDFLARE_ACCOUNT_ID.")


async def _get_cloudflare_public_url(account_id: str, bucket_name: str) -> str:
    global _CACHED_CF_PUBLIC_URL
    if settings.cloudflare_r2_public_url:
        return settings.cloudflare_r2_public_url
    async with _CF_CACHE_LOCK:
        if _CACHED_CF_PUBLIC_URL:
            return _CACHED_CF_PUBLIC_URL
        token = settings.cloudflare_api_token
        if not token:
            raise ValueError("Cloudflare API token not configured")
        headers = {"Authorization": f"Bearer {token}"}
        async with ClientSession(timeout=ClientTimeout(total=15)) as session:
            try:
                async with session.get(
                    f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket_name}/domains/custom",
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        domains = data.get("result", {}).get("domains", [])
                        if domains and "domain" in domains[0]:
                            _CACHED_CF_PUBLIC_URL = f"https://{domains[0]['domain']}"
                            return _CACHED_CF_PUBLIC_URL
            except Exception:
                pass
            try:
                async with session.get(
                    f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket_name}/domains/managed",
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        domain = result.get("domain")
                        if domain:
                            if not result.get("enabled"):
                                try:
                                    await session.put(
                                        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket_name}/domains/managed",
                                        headers={**headers, "Content-Type": "application/json"},
                                        json={"enabled": True},
                                    )
                                except Exception:
                                    pass
                            _CACHED_CF_PUBLIC_URL = f"https://{domain}"
                            return _CACHED_CF_PUBLIC_URL
            except Exception:
                pass
        raise ValueError("Could not determine Cloudflare R2 public download URL. Please set CLOUDFLARE_R2_PUBLIC_URL.")


def _build_target_queue() -> Deque[str]:
    configured = list(settings.upload_targets or ())
    if not configured:
        configured = [settings.upload_target or "pixeldrain"]

    queue: list[str] = []
    for candidate in configured:
        normalized = candidate.lower()
        if normalized in {"r2", "cloudflare_r2"}:
            normalized = "cloudflare"
        if normalized not in ALLOWED_TARGETS:
            continue
        if normalized == "pixeldrain" and not settings.pixeldrain_key:
            continue
        if normalized == "gofile" and not settings.gofile_token:
            continue
        if normalized == "cloudflare" and not settings.cloudflare_api_token:
            continue
        if normalized not in queue:
            queue.append(normalized)

    if not queue:
        if settings.cloudflare_api_token:
            queue.append("cloudflare")
        elif settings.pixeldrain_key:
            queue.append("pixeldrain")
        else:
            queue.append("gofile")
    elif not settings.upload_targets_defined:
        if settings.cloudflare_api_token and "cloudflare" not in queue:
            queue.append("cloudflare")
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
                if target in {"cloudflare", "r2", "cloudflare_r2"}:
                    link = await _upload_to_cloudflare_async(task, upload_path)
                elif target == "gofile":
                    link = await _upload_to_gofile_async(task, upload_path)
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


async def _upload_to_cloudflare_async(task: MirrorTask, filepath: str) -> str:
    _ensure_not_cancelled(task)
    account_id = await _get_cloudflare_account_id()
    bucket_name = settings.cloudflare_r2_bucket or "mirror"
    filename = os.path.basename(filepath)
    object_key = f"{task.task_id}/{filename}"
    encoded_key = quote(object_key, safe="/")

    total_size = os.path.getsize(filepath)
    task.total_bytes = total_size
    task.downloaded_bytes = 0

    if settings.cloudflare_r2_access_key_id and settings.cloudflare_r2_secret_access_key:
        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        content_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
        loop = asyncio.get_running_loop()
        start_time = time.time()

        def sync_s3_upload():
            import boto3
            from botocore.config import Config
            from boto3.s3.transfer import TransferConfig

            s3 = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=settings.cloudflare_r2_access_key_id,
                aws_secret_access_key=settings.cloudflare_r2_secret_access_key,
                config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
                region_name="auto",
            )

            class S3ProgressCallback:
                def __init__(self):
                    self.transferred = 0

                def __call__(self, bytes_amount):
                    if task.cancel_requested:
                        raise MirrorCancelled(_cancel_reason(task))
                    self.transferred += bytes_amount
                    task.downloaded_bytes = min(self.transferred, task.total_bytes or self.transferred)
                    if task.total_bytes:
                        task.progress = min(99.0, (task.downloaded_bytes / task.total_bytes) * 100)
                    elapsed = time.time() - start_time
                    if elapsed > 0:
                        task.speed = task.downloaded_bytes / elapsed
                    asyncio.run_coroutine_threadsafe(task.update_message(), loop)

            transfer_config = TransferConfig(
                multipart_threshold=8 * 1024 * 1024,
                multipart_chunksize=8 * 1024 * 1024,
                max_concurrency=6,
                use_threads=True,
            )
            extra_args = {"ContentType": content_type}
            cb = S3ProgressCallback()
            s3.upload_file(
                Filename=filepath,
                Bucket=bucket_name,
                Key=object_key,
                ExtraArgs=extra_args,
                Config=transfer_config,
                Callback=cb,
            )

        print(f"[MIRROR] Task {task.task_id} uploading {filepath} ({total_size} bytes) via Cloudflare R2 S3 multipart")
        await asyncio.to_thread(sync_s3_upload)
    else:
        token = settings.cloudflare_api_token
        if not token:
            raise ValueError("Cloudflare API token or R2 S3 keys not configured")

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

        content_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        }
        upload_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket_name}/objects/{encoded_key}"
        timeout = ClientTimeout(total=3600)

        async with ClientSession(timeout=timeout) as session:
            async with session.put(upload_url, data=file_generator(), headers=headers) as resp:
                text = await resp.text()
                if resp.status not in (200, 201):
                    raise ValueError(f"Cloudflare R2 upload failed ({resp.status}): {text}")
                try:
                    payload = json.loads(text)
                    if not payload.get("success", False):
                        errors = payload.get("errors", [])
                        error_msg = "; ".join(e.get("message", "") for e in errors) if errors else text
                        raise ValueError(f"Cloudflare R2 returned error: {error_msg}")
                except json.JSONDecodeError:
                    raise ValueError(f"Cloudflare R2 returned unexpected response: {text}")

    task.downloaded_bytes = task.total_bytes
    task.progress = 100.0
    task.speed = None
    await task.update_message(force=True)

    public_base = await _get_cloudflare_public_url(account_id, bucket_name)
    public_base = public_base.rstrip("/")
    return f"{public_base}/{encoded_key}"


async def _upload_to_gofile_async(task: MirrorTask, filepath: str) -> str:
    _ensure_not_cancelled(task)
    if not settings.gofile_token:
        raise ValueError("GoFile token not configured")

    filename = os.path.basename(filepath)
    total_size = os.path.getsize(filepath)
    task.total_bytes = total_size
    task.downloaded_bytes = 0
    start = time.time()

    endpoints = settings.gofile_upload_endpoints or ("https://upload.gofile.io/uploadfile",)
    errors: list[str] = []
    folder_id = settings.gofile_folder_id.strip()
    timeout = ClientTimeout(total=1800)

    for endpoint in endpoints:
        _ensure_not_cancelled(task)
        headers = {"Authorization": f"Bearer {settings.gofile_token}"}

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

        form = aiohttp.FormData()
        if folder_id:
            form.add_field("folderId", folder_id)
        form.add_field("file", file_generator(), filename=filename)

        try:
            async with ClientSession(timeout=timeout) as session:
                async with session.post(endpoint, data=form, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status >= 500:
                        errors.append(f"{endpoint}: {resp.status} {text}")
                        print(f"[MIRROR] GoFile server error via {endpoint}: {resp.status} {text}")
                        continue
                    if resp.status == 401:
                        raise ValueError("GoFile authentication failed (401). Check API token.")
                    try:
                        json_payload = json.loads(text)
                    except json.JSONDecodeError:
                        errors.append(f"{endpoint}: non-JSON response {text}")
                        print(f"[MIRROR] GoFile non-JSON response via {endpoint}: {text}")
                        continue

                    status = (json_payload.get("status") or "").lower()
                    if status and status != "ok":
                        message = json_payload.get("message") or json_payload.get("error") or text
                        errors.append(f"{endpoint}: {status} {message}")
                        print(f"[MIRROR] GoFile API error via {endpoint}: {status} {message}")
                        continue

                    payload = json_payload.get("data") or {}
                    link = payload.get("downloadPage") or payload.get("directLink")
                    if link:
                        task.downloaded_bytes = task.total_bytes
                        task.progress = 100.0
                        task.speed = None
                        await task.update_message(force=True)
                        return link

                    errors.append(f"{endpoint}: missing link in response {json_payload}")
                    print(f"[MIRROR] GoFile missing link via {endpoint}: {json_payload}")
        except MirrorCancelled:
            raise
        except Exception as exc:
            error_message = f"request error: {exc}"
            errors.append(f"{endpoint}: {error_message}")
            print(f"[MIRROR] GoFile request error via {endpoint}: {exc}")
            continue

    raise ValueError("GoFile upload failed: " + "; ".join(errors))


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


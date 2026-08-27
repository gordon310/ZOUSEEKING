"""Private Supabase Storage adapter for anonymous intake files."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_UPLOADS = {
    "application/pdf": ((".pdf",), b"%PDF-"),
    "image/jpeg": ((".jpg", ".jpeg"), b"\xff\xd8\xff"),
    "image/png": ((".png",), b"\x89PNG\r\n\x1a\n"),
}
STORAGE_ERROR_MESSAGE = "文件服务暂时不可用，请稍后重试。"


class UnsupportedUpload(ValueError):
    """The uploaded file is outside the supported type or size boundary."""


class StorageUnavailable(RuntimeError):
    """Storage could not complete the request without exposing remote details."""

    def __init__(self, message: str = STORAGE_ERROR_MESSAGE) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class StorageObject:
    path: str
    original_name: str
    media_type: str
    size_bytes: int
    content_hash: str


def validate_upload(filename: str, media_type: str, content: bytes) -> str:
    if not filename or "/" in filename or "\\" in filename:
        raise UnsupportedUpload("文件名不合法。")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise UnsupportedUpload("文件为空或超过 20 MiB 限制。")
    allowed = ALLOWED_UPLOADS.get(media_type)
    if not allowed:
        raise UnsupportedUpload("仅支持 PDF、JPG、PNG 文件。")
    extensions, magic = allowed
    extension = PurePosixPath(filename).suffix.lower()
    if extension not in extensions or not content.startswith(magic):
        raise UnsupportedUpload("文件扩展名与内容类型不匹配。")
    return extension


def _config() -> tuple[str, str, str]:
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("INTAKE_BUCKET", "property-intake").strip()
    if not base_url or not service_key or not bucket:
        raise StorageUnavailable()
    return base_url, service_key, bucket


def _object_path(session_id: str, extension: str) -> str:
    if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
        raise StorageUnavailable()
    return f"{session_id}/{uuid4()}{extension}"


def upload_private_file(session_id: str, filename: str, media_type: str, content: bytes) -> StorageObject:
    extension = validate_upload(filename, media_type, content)
    base_url, service_key, bucket = _config()
    path = _object_path(session_id, extension)
    request = Request(
        f"{base_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(path, safe='/')}",
        data=content,
        method="POST",
        headers={
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
            "Content-Type": media_type,
            "x-upsert": "false",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            if getattr(response, "status", 200) >= 400:
                raise StorageUnavailable()
    except StorageUnavailable:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise StorageUnavailable() from exc
    return StorageObject(
        path=path,
        original_name=filename,
        media_type=media_type,
        size_bytes=len(content),
        content_hash=hashlib.sha256(content).hexdigest(),
    )


def delete_private_file(path: str) -> None:
    parts = path.split("/")
    if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
        raise StorageUnavailable()
    base_url, service_key, bucket = _config()
    request = Request(
        f"{base_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(path, safe='/')}",
        method="DELETE",
        headers={
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            if getattr(response, "status", 200) >= 400:
                raise StorageUnavailable()
    except StorageUnavailable:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise StorageUnavailable() from exc

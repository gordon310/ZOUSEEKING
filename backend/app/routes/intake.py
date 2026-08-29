"""FastAPI boundary for anonymous Osaka property intake."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Header, HTTPException, Request, UploadFile

from ..auth import AuthUser, require_user
from ..db import get_pool
from ..intake import storage as storage_module
from ..intake.completeness import build_free_preview
from ..intake.geocoding import GsiReverseGeocoder, ReverseGeocoderError
from ..intake.models import (
    ConfirmFieldRequest,
    ConvertSessionRequest,
    CreateInputRequest,
    CreateInputResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    FieldView,
    LocationRequest,
    LocationResponse,
    FreePreviewResponse,
)
from ..intake.repository import (
    DuplicateAddress,
    IntakeRepository,
    ProjectNameRequired,
    ProjectNameTaken,
    SessionNotFound,
)
from ..intake.tokens import hash_session_token, new_session_token
from ..intake.storage import (
    MAX_UPLOAD_BYTES,
    StorageUnavailable,
    UnsupportedUpload,
    validate_upload,
)


router = APIRouter(prefix="/api/intake", tags=["intake"])

SESSION_NOT_FOUND_MESSAGE = "分析项目不存在或已过期。"
RATE_LIMIT_MESSAGE = "操作太频繁，请稍后再试。"
STORAGE_FAILURE_MESSAGE = "文件服务暂时不可用，请稍后重试。"
SAVE_FAILURE_MESSAGE = "资料保存失败，请稍后重试。"
LOCATION_FAILURE_MESSAGE = "位置资料保存失败，请稍后重试。"
DUPLICATE_ADDRESS_MESSAGE = "同一地址已有调查记录，请手工修改记录名称。"
PROJECT_NAME_TAKEN_MESSAGE = "这个调查记录名称已存在，请换一个名称。"
PROJECT_NAME_REQUIRED_MESSAGE = "请先确认地址，或手工填写调查记录名称。"
SESSION_TTL = timedelta(hours=24)


def get_intake_repository() -> IntakeRepository:
    return IntakeRepository(get_pool())


def get_storage() -> Any:
    return storage_module


def get_reverse_geocoder() -> GsiReverseGeocoder:
    return GsiReverseGeocoder()


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, default)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=SESSION_NOT_FOUND_MESSAGE)


def _token_digest(raw_token: Optional[str]) -> str:
    if not raw_token:
        raise _not_found()
    try:
        return hash_session_token(raw_token)
    except ValueError as exc:
        raise _not_found() from exc


async def _require_session(repository: IntakeRepository, session_id: UUID, raw_token: Optional[str]) -> Any:
    try:
        return await repository.require_session(session_id, _token_digest(raw_token))
    except SessionNotFound as exc:
        raise _not_found() from exc


async def _require_editable_session(
    repository: IntakeRepository, session_id: UUID, raw_token: Optional[str]
) -> Any:
    session = await _require_session(repository, session_id, raw_token)
    if str(_row_value(session, "status", "")) == "converted":
        raise _not_found()
    return session


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _abuse_key_hash(request: Request, scope: str = "source") -> str:
    salt = os.getenv("ABUSE_HASH_SALT", "").strip()
    if not salt and os.getenv("ENVIRONMENT", "").lower() != "test":
        raise HTTPException(status_code=503, detail="服务尚未配置")
    if not salt:
        salt = "test-only-abuse-salt"
    host = request.client.host if request.client else "unknown"
    raw_key = f"{scope}:{host}"
    return hmac.new(salt.encode("utf-8"), raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


async def _enforce_rate_limit(
    repository: IntakeRepository,
    request: Request,
    action: str,
    limit: int,
    scope: str = "source",
) -> None:
    now = _now()
    window_started_at = now.replace(minute=0, second=0, microsecond=0)
    count = await repository.consume_rate_limit(
        _abuse_key_hash(request, scope),
        action,
        window_started_at,
        limit,
        window_started_at + timedelta(hours=1),
    )
    if count is None:
        raise HTTPException(
            status_code=429,
            detail=RATE_LIMIT_MESSAGE,
            headers={"Retry-After": "3600"},
        )


async def cleanup_expired_sessions(repository: IntakeRepository, storage: Any) -> None:
    try:
        paths = await repository.expire_sessions(limit=100)
    except Exception:
        return
    for path in paths:
        try:
            storage.delete_private_file(path)
        except StorageUnavailable:
            continue


def _uuid_value(row: Any, name: str) -> UUID:
    value = _row_value(row, name)
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _input_response(row: Any) -> CreateInputResponse:
    return CreateInputResponse(
        input_id=_uuid_value(row, "id"),
        processing_status=str(_row_value(row, "processing_status", "pending")),
    )


def _location_response(row: Any, request: LocationRequest) -> LocationResponse:
    return LocationResponse(
        latitude=float(_row_value(row, "latitude", request.latitude)),
        longitude=float(_row_value(row, "longitude", request.longitude)),
        accuracy_m=float(_row_value(row, "location_accuracy_m", request.accuracy_m)),
        captured_at=_row_value(row, "location_captured_at") or request.captured_at,
        location_source=str(_row_value(row, "location_source", request.source)),
        address_candidate=str(_row_value(row, "address_candidate", "") or ""),
        address_source=str(_row_value(row, "address_source", "unavailable") or "unavailable"),
        address_precision=str(_row_value(row, "address_precision", "") or ""),
    )


@router.post("/sessions", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    payload: CreateSessionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    repository: IntakeRepository = Depends(get_intake_repository),
    storage: Any = Depends(get_storage),
) -> CreateSessionResponse:
    await _enforce_rate_limit(repository, request, "session_create", 10)
    token = new_session_token()
    created_at = _now()
    expires_at = created_at + SESSION_TTL
    row = await repository.create_session(
        payload.purpose,
        payload.consent_version,
        token.digest,
        expires_at,
    )
    if not row:
        raise HTTPException(status_code=503, detail="分析服务暂时不可用，请稍后重试。")
    background_tasks.add_task(cleanup_expired_sessions, repository, storage)
    return CreateSessionResponse(
        session_id=_uuid_value(row, "id"),
        session_token=token.raw,
        expires_at=expires_at,
        expires_in_seconds=int(SESSION_TTL.total_seconds()),
    )


@router.post("/sessions/{session_id}/inputs", response_model=CreateInputResponse, status_code=201)
async def add_input(
    session_id: UUID,
    payload: CreateInputRequest,
    request: Request,
    x_analysis_session: Optional[str] = Header(default=None, alias="X-Analysis-Session"),
    repository: IntakeRepository = Depends(get_intake_repository),
) -> CreateInputResponse:
    await _require_editable_session(repository, session_id, x_analysis_session)
    await _enforce_rate_limit(repository, request, "input_create", 30)
    row = await repository.add_input(session_id, payload)
    if not row:
        raise HTTPException(status_code=503, detail=SAVE_FAILURE_MESSAGE)
    return _input_response(row)


@router.post("/sessions/{session_id}/files", response_model=CreateInputResponse, status_code=201)
async def add_file(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    x_analysis_session: Optional[str] = Header(default=None, alias="X-Analysis-Session"),
    repository: IntakeRepository = Depends(get_intake_repository),
    storage: Any = Depends(get_storage),
) -> CreateInputResponse:
    await _require_editable_session(repository, session_id, x_analysis_session)
    await _enforce_rate_limit(repository, request, "file_upload", 10)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件大小不能超过 20 MiB。")
    try:
        validate_upload(file.filename or "", file.content_type or "", content)
    except UnsupportedUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        stored = storage.upload_private_file(
            str(session_id),
            file.filename or "",
            file.content_type or "",
            content,
        )
    except UnsupportedUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=STORAGE_FAILURE_MESSAGE) from exc

    try:
        row = await repository.add_file_input(session_id, stored)
    except Exception as exc:
        try:
            storage.delete_private_file(stored.path)
        except StorageUnavailable:
            pass
        raise HTTPException(status_code=503, detail=SAVE_FAILURE_MESSAGE) from exc
    if not row:
        try:
            storage.delete_private_file(stored.path)
        except StorageUnavailable:
            pass
        raise HTTPException(status_code=503, detail=SAVE_FAILURE_MESSAGE)
    return _input_response(row)


@router.put("/sessions/{session_id}/location", response_model=LocationResponse)
async def save_location(
    session_id: UUID,
    payload: LocationRequest,
    request: Request,
    x_analysis_session: Optional[str] = Header(default=None, alias="X-Analysis-Session"),
    repository: IntakeRepository = Depends(get_intake_repository),
    reverse_geocoder: GsiReverseGeocoder = Depends(get_reverse_geocoder),
) -> LocationResponse:
    await _require_editable_session(repository, session_id, x_analysis_session)
    await _enforce_rate_limit(repository, request, "location_capture", 5, scope=f"session:{session_id}")
    candidate = None
    try:
        candidate = await asyncio.to_thread(
            reverse_geocoder.reverse_geocode,
            payload.latitude,
            payload.longitude,
        )
    except ReverseGeocoderError:
        candidate = None
    try:
        row = await repository.save_location(session_id, payload, candidate)
    except SessionNotFound as exc:
        raise _not_found() from exc
    if not row:
        raise HTTPException(status_code=503, detail=LOCATION_FAILURE_MESSAGE)
    return _location_response(row, payload)


@router.put("/sessions/{session_id}/fields/{field_name}", response_model=FieldView)
async def confirm_field(
    session_id: UUID,
    field_name: str,
    payload: ConfirmFieldRequest,
    x_analysis_session: Optional[str] = Header(default=None, alias="X-Analysis-Session"),
    repository: IntakeRepository = Depends(get_intake_repository),
) -> FieldView:
    await _require_editable_session(repository, session_id, x_analysis_session)
    if payload.field_name != field_name:
        raise HTTPException(status_code=422, detail="字段路径与请求字段不一致。")
    try:
        row = await repository.upsert_field(session_id, payload)
    except SessionNotFound as exc:
        raise _not_found() from exc
    if not row:
        raise HTTPException(status_code=503, detail=SAVE_FAILURE_MESSAGE)
    return FieldView(
        field_name=str(_row_value(row, "field_name", payload.field_name)),
        value=_row_value(row, "confirmed_value", payload.value),
        unit=_row_value(row, "unit", payload.unit),
        source_input_id=_row_value(row, "source_input_id", payload.source_input_id),
        locator=str(_row_value(row, "locator", payload.locator)),
        confirmation_status=str(_row_value(row, "confirmation_status", payload.confirmation_status)),
        confidence=str(_row_value(row, "confidence", "unreviewed")),
    )


@router.post("/sessions/{session_id}/preview", response_model=FreePreviewResponse)
async def create_preview(
    session_id: UUID,
    request: Request,
    x_analysis_session: Optional[str] = Header(default=None, alias="X-Analysis-Session"),
    repository: IntakeRepository = Depends(get_intake_repository),
) -> FreePreviewResponse:
    await _require_editable_session(repository, session_id, x_analysis_session)
    await _enforce_rate_limit(repository, request, "preview_create", 20, scope=f"session:{session_id}")
    fields = await repository.get_fields(session_id)
    preview = build_free_preview(fields)
    await repository.save_preview(session_id, preview)
    return FreePreviewResponse(session_id=session_id, **preview)


@router.post("/sessions/{session_id}/convert")
async def convert_session(
    session_id: UUID,
    payload: Optional[ConvertSessionRequest] = Body(default=None),
    x_analysis_session: Optional[str] = Header(default=None, alias="X-Analysis-Session"),
    user: AuthUser = Depends(require_user),
    repository: IntakeRepository = Depends(get_intake_repository),
) -> Dict[str, str]:
    try:
        converted = await repository.convert_to_user(
            session_id,
            _token_digest(x_analysis_session),
            user.user_id,
            payload.project_name if payload else None,
        )
    except SessionNotFound as exc:
        raise _not_found() from exc
    except ProjectNameRequired as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "project_name_required", "message": PROJECT_NAME_REQUIRED_MESSAGE},
        ) from exc
    except DuplicateAddress as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_address", "message": DUPLICATE_ADDRESS_MESSAGE},
        ) from exc
    except ProjectNameTaken as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "project_name_taken", "message": PROJECT_NAME_TAKEN_MESSAGE},
        ) from exc
    return {
        "owner_user_id": str(converted.owner_user_id),
        "property_id": str(converted.property_id),
    }


@router.get("/projects/{property_id}")
async def get_project(
    property_id: UUID,
    user: AuthUser = Depends(require_user),
    repository: IntakeRepository = Depends(get_intake_repository),
) -> Dict[str, Any]:
    try:
        row = await repository.get_project(property_id, user.user_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问。") from exc
    return dict(row)

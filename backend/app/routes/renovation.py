"""FastAPI endpoints for Japanese interior renovation rough estimates."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError

from ..intake.storage import MAX_UPLOAD_BYTES, UnsupportedUpload, validate_upload
from ..renovation.models import (
    PhotoRecord,
    RenovationEstimateRequest,
    RenovationEstimateResponse,
    RenovationUploadManifest,
)
from ..renovation.pricing import build_estimate
from ..renovation.vision import VisionInput, VisionProviderUnavailable, get_vision_provider
from .intake import _enforce_rate_limit, get_intake_repository


router = APIRouter(prefix="/api/renovation", tags=["renovation"])


def _bad_manifest(exc: ValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "invalid_manifest", "errors": exc.errors()})


def _validate_image(filename: str, media_type: str, content: bytes) -> None:
    if media_type not in {"image/jpeg", "image/png"}:
        raise UnsupportedUpload("装修分析只支持 JPG、PNG 图片。")
    validate_upload(filename, media_type, content)


@router.post("/estimates", response_model=RenovationEstimateResponse)
async def create_estimate(
    payload: RenovationEstimateRequest,
    request: Request,
    repository: Any = Depends(get_intake_repository),
) -> Dict[str, object]:
    await _enforce_rate_limit(repository, request, "renovation_estimate", 30, scope="renovation")
    return build_estimate(payload)


@router.post("/analyses", response_model=RenovationEstimateResponse)
async def analyze_uploaded_images(
    request: Request,
    manifest: str = Form(...),
    images: List[UploadFile] = File(...),
    repository: Any = Depends(get_intake_repository),
) -> Dict[str, object]:
    await _enforce_rate_limit(repository, request, "renovation_image_analysis", 10, scope="renovation")
    try:
        parsed_manifest = RenovationUploadManifest.model_validate_json(manifest)
    except ValidationError as exc:
        raise _bad_manifest(exc) from exc

    by_filename = {photo.filename: photo for photo in parsed_manifest.photos}
    uploaded_filenames = [image.filename for image in images]
    if (
        len(images) != len(parsed_manifest.photos)
        or len(set(uploaded_filenames)) != len(uploaded_filenames)
        or set(uploaded_filenames) != set(by_filename)
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": "image_manifest_mismatch", "message": "上传图片必须与 manifest 中的 filename 一一对应。"},
        )

    uploaded: List[VisionInput] = []
    for image in images:
        content = await image.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="图片大小不能超过 20 MiB。")
        try:
            _validate_image(image.filename or "", image.content_type or "", content)
        except UnsupportedUpload as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        photo = by_filename[image.filename or ""]
        uploaded.append(VisionInput(photo.id, photo.room, image.filename or "", image.content_type or "", content))

    if any(photo.observations for photo in parsed_manifest.photos):
        estimate_request = RenovationEstimateRequest(
            context=parsed_manifest.context,
            photos=[
                PhotoRecord.model_validate(photo.model_dump(exclude={"filename"}))
                for photo in parsed_manifest.photos
            ],
        )
        return build_estimate(estimate_request, analysis_source="structured_observations")

    provider = get_vision_provider()
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "vision_provider_not_configured",
                "message": "图片状态识别服务尚未配置；可先在 /api/renovation/estimates 提交结构化照片观察。",
            },
        )
    try:
        recognized = await asyncio.to_thread(provider.analyze, uploaded, parsed_manifest.context)
    except VisionProviderUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "vision_provider_unavailable", "message": "图片状态识别服务暂时不可用，请稍后重试。"},
        ) from exc
    estimate_request = RenovationEstimateRequest(context=parsed_manifest.context, photos=recognized)
    return build_estimate(estimate_request, analysis_source="vision_provider")

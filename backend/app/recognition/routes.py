from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..auth import AuthUser, require_user
from . import service


router = APIRouter(prefix="/api/recognition", tags=["recognition"])


class RecognitionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    image: str
    note: str = Field(default="", max_length=1000)
    resolve_location_only: bool = False
    use_ai: bool = False

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        try:
            service.validate_image_data_url(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return value


@router.post("", response_model=dict[str, Any])
async def recognize_listing(payload: dict[str, Any], _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        validated = RecognitionRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_image", "message": "图片必须是有效的 JPEG、PNG 或 WEBP data URL，解码后不能超过 2 MiB。"},
        ) from exc
    try:
        recognized = await service.recognize(
            validated.image,
            validated.note,
            resolve_location_only=validated.resolve_location_only,
            use_ai=validated.use_ai,
        )
    except service.RecognitionNotConfigured as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "recognition_not_configured", "message": "AI 识别服务尚未配置。"},
        ) from exc
    except service.RecognitionUpstreamTimeout as exc:
        raise HTTPException(
            status_code=504,
            detail={"code": "recognition_upstream_timeout", "message": "AI 识别服务响应超时，请稍后重试。"},
        ) from exc
    except service.RecognitionUpstreamError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "recognition_upstream_error", "message": "AI 识别服务暂时不可用，请稍后重试。"},
        ) from exc
    return recognized

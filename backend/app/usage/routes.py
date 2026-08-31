"""FastAPI usage boundary with disabled-by-default quota wiring."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..auth import AuthUser, require_user
from .ledger import (
    IdempotencyConflict,
    LedgerResult,
    QuotaExceeded,
    ReservationNotFound,
    ReservationStateError,
    UsageKind,
)
from .service import UsageService


Operation = Literal["consume", "reserve", "commit", "release"]
Period = Literal["day", "month"]
router = APIRouter(prefix="/api/usage", tags=["usage"])


class UsageRequest(BaseModel):
    """Client input; ownership, scope, actor, and limit are server-derived."""

    model_config = ConfigDict(extra="forbid")

    kind: UsageKind
    units: int = Field(gt=0)
    operation: Operation = "consume"
    period: Period = "day"
    reservation_key: Optional[str] = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_reservation(self) -> "UsageRequest":
        if self.reservation_key is not None and not self.reservation_key.strip():
            raise ValueError("reservation_key must not be blank")
        if self.operation in {"commit", "release"} and self.reservation_key is None:
            raise ValueError("reservation_key is required for a reservation transition")
        if self.operation == "reserve" and self.reservation_key is not None:
            raise ValueError("reservation_key is assigned by the server from Idempotency-Key")
        return self


class UsageResponse(BaseModel):
    status: str
    event_id: UUID
    period_id: UUID
    scope_type: str
    kind: UsageKind
    units: int
    consumed_units: int
    reserved_units: int
    limit_units: int
    period_start: datetime
    period_end: datetime


def get_usage_service() -> UsageService:
    """Provider/database wiring remains absent until a later rollout gate."""

    raise HTTPException(status_code=503, detail="usage service is not configured")


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def _to_response(result: LedgerResult) -> UsageResponse:
    return UsageResponse(
        status=result.status,
        event_id=result.event_id,
        period_id=result.period_id,
        scope_type=result.scope.kind,
        kind=result.kind,
        units=result.units,
        consumed_units=result.consumed,
        reserved_units=result.reserved,
        limit_units=result.limit,
        period_start=result.period_start,
        period_end=result.period_end,
    )


@router.post("/events", response_model=UsageResponse)
async def apply_usage(
    request: UsageRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    user: AuthUser = Depends(require_user),
    service: UsageService = Depends(get_usage_service),
) -> Any:
    request_key = idempotency_key.strip()
    if not request_key:
        return _error(422, "invalid_request", "Idempotency-Key must not be blank")
    try:
        result = service.apply(user.user_id, request_key, request)
    except QuotaExceeded:
        return _error(429, "quota_exceeded", "usage quota exceeded")
    except IdempotencyConflict:
        return _error(409, "idempotency_conflict", "request key conflict")
    except ReservationNotFound:
        return _error(409, "reservation_not_found", "reservation not found")
    except ReservationStateError:
        return _error(409, "reservation_not_active", "reservation is no longer active")
    except ValueError:
        return _error(422, "invalid_usage_request", "invalid usage request")
    except Exception:
        return _error(503, "usage_unavailable", "usage service unavailable")
    return _to_response(result)

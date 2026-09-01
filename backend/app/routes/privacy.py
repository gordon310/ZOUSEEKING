from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal

from ..auth import AuthUser, require_user
from ..services.privacy import (
    DeletionServiceUnavailable,
    PRIVACY_POLICY_VERSION,
    TERMS_VERSION,
    privacy_metadata,
)


router = APIRouter()


class AccountDeletionRequest(BaseModel):
    # Ignore optional client fields instead of echoing them in Pydantic 422 bodies.
    # Ownership always comes from the verified bearer user, never request JSON.
    model_config = ConfigDict(extra="ignore")

    privacy_policy_version: str = Field(min_length=1, max_length=100)
    terms_version: str = Field(min_length=1, max_length=100)
    confirmation: Literal["DELETE_ACCOUNT"]


class UnavailableDeletionExecutor:
    async def submit(self, user: AuthUser, *, requested_at: datetime) -> dict[str, Any]:
        raise DeletionServiceUnavailable()


_deletion_executor = UnavailableDeletionExecutor()
_PUBLIC_DELETION_RECEIPT_FIELDS = {
    "status",
    "request_id",
    "policy_version",
    "terms_version",
    "requested_at",
    "acknowledgement_due",
    "access_restriction_due",
    "primary_data_deletion_due",
    "backup_expiry_due",
}


def get_deletion_executor() -> UnavailableDeletionExecutor:
    """Dependency seam for a reviewed, trusted executor in a later release."""

    return _deletion_executor


@router.get("/api/privacy")
async def get_privacy_metadata() -> dict[str, Any]:
    return privacy_metadata()


@router.post("/api/account/deletion-request", status_code=202)
async def request_account_deletion(
    payload: AccountDeletionRequest,
    user: AuthUser = Depends(require_user),
    executor: Any = Depends(get_deletion_executor),
) -> dict[str, Any]:
    if (
        payload.privacy_policy_version != PRIVACY_POLICY_VERSION
        or payload.terms_version != TERMS_VERSION
    ):
        raise HTTPException(status_code=409, detail="please accept the current privacy and terms versions")

    try:
        receipt = await executor.submit(user, requested_at=datetime.now(timezone.utc))
    except DeletionServiceUnavailable:
        raise HTTPException(
            status_code=503,
            detail="account deletion service is not configured; no account data was changed",
        ) from None
    except Exception:
        # Do not expose executor/database/Auth details through this endpoint.
        raise HTTPException(
            status_code=503,
            detail="account deletion service is temporarily unavailable; no account data was changed",
        ) from None
    if not isinstance(receipt, Mapping):
        raise HTTPException(
            status_code=503,
            detail="account deletion service is temporarily unavailable; no account data was changed",
        )
    return {key: receipt[key] for key in _PUBLIC_DELETION_RECEIPT_FIELDS if key in receipt}

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal

from ..auth import AuthUser, require_user
from ..services.account_deletion import ControlledDeletionExecutor
from ..services.policy_consent import PolicyConsentStore
from ..services.privacy import (
    DeletionServiceUnavailable,
    PRIVACY_POLICY_VERSION,
    TERMS_VERSION,
    privacy_metadata,
)


router = APIRouter()


class PolicyConsentRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    privacy_policy_version: str = Field(min_length=1, max_length=100)
    terms_version: str = Field(min_length=1, max_length=100)


def get_consent_store() -> PolicyConsentStore:
    return PolicyConsentStore()


@router.get("/api/account/consent")
async def get_policy_consent(user: AuthUser = Depends(require_user), store: Any = Depends(get_consent_store)) -> dict:
    try:
        accepted = await store.status(user.user_id)
    except Exception:
        raise HTTPException(503, "policy confirmation temporarily unavailable") from None
    return {"accepted": accepted, "privacy_policy_version": PRIVACY_POLICY_VERSION, "terms_version": TERMS_VERSION}


@router.post("/api/account/consent")
async def accept_policy_consent(payload: PolicyConsentRequest, user: AuthUser = Depends(require_user), store: Any = Depends(get_consent_store)) -> dict:
    if payload.privacy_policy_version != PRIVACY_POLICY_VERSION or payload.terms_version != TERMS_VERSION:
        raise HTTPException(409, "please accept the current privacy and terms versions")
    try:
        return await store.accept(user.user_id)
    except Exception:
        raise HTTPException(503, "policy confirmation temporarily unavailable") from None


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


_deletion_executor = ControlledDeletionExecutor()
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


def get_deletion_executor() -> Any:
    """Dependency seam for the trusted controlled deletion executor."""

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

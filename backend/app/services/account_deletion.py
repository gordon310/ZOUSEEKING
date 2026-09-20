"""Controlled account deletion: retain audit facts, remove identity value."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from ..auth import AuthUser
from ..db import get_pool
from ..integrations.supabase_admin import SupabaseAdmin, SupabaseAdminError
from .privacy import (
    ACKNOWLEDGEMENT_SLA,
    ACCESS_RESTRICTION_SLA,
    BACKUP_EXPIRY_SLA,
    PRIMARY_DATA_DELETION_SLA,
    PRIVACY_POLICY_VERSION,
    TERMS_VERSION,
    DeletionServiceUnavailable,
)

logger = logging.getLogger(__name__)
_UTC = timezone.utc


class AccountDeletionExecutionError(RuntimeError):
    """Safe internal error mapped to the route's generic 503."""


class ControlledDeletionExecutor:
    def __init__(self, *, pool: Any | None = None, auth_admin: Any | None = None) -> None:
        self.pool = pool
        self.auth_admin = auth_admin or SupabaseAdmin()

    async def submit(self, user: AuthUser, *, requested_at: datetime) -> dict[str, Any]:
        if not self.auth_admin.is_configured():
            raise DeletionServiceUnavailable()
        requested = self._utc(requested_at)
        pool = self.pool or get_pool()
        row = await self._open_or_resume(pool, user.user_id, requested)
        if row["status"] == "completed":
            return self._receipt(row)
        request_id = row["id"]
        await self._set_executing(pool, request_id)
        stage = "auth_revoke_failed"
        try:
            await self.auth_admin.revoke_all_sessions(user.user_id, user.access_token)
            stage = "database_anonymization_failed"
            await self._anonymize_database(pool, user.user_id)
            # Delete the Auth identity only after application-owned rows have
            # been removed or de-identified. The usage_events FK then performs
            # its narrowly permitted actor_user_id -> NULL anonymization.
            stage = "auth_deletion_failed"
            await self.auth_admin.delete_user(user.user_id)
            row = await self._complete(pool, request_id)
            return self._receipt(row)
        except (SupabaseAdminError, AccountDeletionExecutionError):
            await self._mark_failed(pool, request_id, stage)
            raise AccountDeletionExecutionError(stage) from None
        except Exception:
            logger.error("account deletion failed category=%s", stage)
            await self._mark_failed(pool, request_id, stage)
            raise AccountDeletionExecutionError(stage) from None

    async def _open_or_resume(self, pool: Any, user_id: UUID, requested: datetime) -> Mapping[str, Any]:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("select pg_advisory_xact_lock(hashtext($1))", f"account-deletion:{user_id}")
                existing = await conn.fetchrow(
                    "select * from public.account_deletion_requests where user_id=$1 order by created_at desc limit 1",
                    user_id,
                )
                if existing:
                    if existing["status"] == "failed":
                        await conn.execute(
                            "update public.account_deletion_requests set status='pending', failure_reason=null, updated_at=now() where id=$1",
                            existing["id"],
                        )
                        existing = dict(existing, status="pending")
                    return existing
                return await conn.fetchrow(
                    """
                    insert into public.account_deletion_requests
                      (user_id, status, policy_version, terms_version, requested_at,
                       acknowledgement_due, access_restriction_due,
                       primary_data_deletion_due, backup_expiry_due)
                    values ($1, 'pending', $2, $3, $4, $5, $6, $7, $8)
                    returning *
                    """,
                    user_id,
                    PRIVACY_POLICY_VERSION,
                    TERMS_VERSION,
                    requested,
                    requested + ACKNOWLEDGEMENT_SLA,
                    requested + ACCESS_RESTRICTION_SLA,
                    requested + PRIMARY_DATA_DELETION_SLA,
                    requested + BACKUP_EXPIRY_SLA,
                )

    async def _set_executing(self, pool: Any, request_id: UUID) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "update public.account_deletion_requests set status='executing', updated_at=now() where id=$1 and status in ('pending','executing')",
                request_id,
            )

    async def _anonymize_database(self, pool: Any, user_id: UUID) -> None:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "update public.user_profiles set email='', username='', display_name='', city='', favorite_area='', favorite_asset_type='', bio='', membership_tier='free', daily_query_limit=0 where user_id=$1",
                    user_id,
                )
                # Generated market reports are retained as de-identified
                # artifacts; private query indexes and workspaces are erased.
                await conn.execute(
                    "update public.property_reports set owner_user_id=null, query_id=null where owner_user_id=$1 or exists (select 1 from public.queries q where q.id=property_reports.query_id and q.owner_user_id=$1)",
                    user_id,
                )
                await conn.execute("delete from public.exports where owner_user_id=$1", user_id)
                await conn.execute("delete from public.analysis_sessions where owner_user_id=$1", user_id)
                await conn.execute("delete from public.queries where owner_user_id=$1", user_id)
                await conn.execute("delete from public.organization_members where user_id=$1", user_id)
                await conn.execute("delete from public.usage_quotas where scope_key=$1", f"user:{user_id}")

    async def _complete(self, pool: Any, request_id: UUID) -> Mapping[str, Any]:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "update public.account_deletion_requests set status='completed', executed_at=now(), failure_reason=null, updated_at=now() where id=$1 returning *",
                request_id,
            )
            if not row:
                raise AccountDeletionExecutionError("ledger_completion_failed")
            return row

    async def _mark_failed(self, pool: Any, request_id: UUID, reason: str) -> None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "update public.account_deletion_requests set status='failed', failure_reason=$2, updated_at=now() where id=$1",
                    request_id,
                    reason,
                )
        except Exception:
            logger.error("account deletion failure ledger update failed category=ledger")

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        return value.astimezone(_UTC)

    @staticmethod
    def _receipt(row: Mapping[str, Any]) -> dict[str, Any]:
        def iso(value: Any) -> str:
            return value.astimezone(_UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

        return {
            "status": row["status"],
            "request_id": str(row["id"]),
            "policy_version": row["policy_version"],
            "terms_version": row["terms_version"],
            "requested_at": iso(row["requested_at"]),
            "acknowledgement_due": iso(row["acknowledgement_due"]),
            "access_restriction_due": iso(row["access_restriction_due"]),
            "primary_data_deletion_due": iso(row["primary_data_deletion_due"]),
            "backup_expiry_due": iso(row["backup_expiry_due"]),
        }

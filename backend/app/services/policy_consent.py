"""Record policy acceptance in the existing append-only audit ledger."""
import json
from uuid import UUID

from ..db import get_pool
from .privacy import PRIVACY_POLICY_VERSION, TERMS_VERSION


class PolicyConsentStore:
    async def _status(self, conn, user_id: UUID) -> bool:
        return bool(await conn.fetchval(
            "select exists(select 1 from public.audit_events where actor_user_id=$1 "
            "and action='privacy.policy.accepted' and summary @> $2::jsonb)",
            user_id, json.dumps({"privacy_policy_version": PRIVACY_POLICY_VERSION, "terms_version": TERMS_VERSION}),
        ))

    async def status(self, user_id: UUID) -> bool:
        async with get_pool().acquire() as conn:
            return await self._status(conn, user_id)

    async def accept(self, user_id: UUID) -> dict:
        async with get_pool().acquire() as conn, conn.transaction():
            await conn.execute("select pg_advisory_xact_lock(hashtextextended($1,0))", f"policy-consent:{user_id}")
            if not await self._status(conn, user_id):
                await conn.execute(
                    "insert into public.audit_events(actor_user_id,action,target_type,target_id,summary) "
                    "values($1,'privacy.policy.accepted','privacy_policy',$2,$3::jsonb)",
                    user_id, PRIVACY_POLICY_VERSION,
                    json.dumps({"privacy_policy_version": PRIVACY_POLICY_VERSION, "terms_version": TERMS_VERSION}),
                )
        return {"accepted": True, "privacy_policy_version": PRIVACY_POLICY_VERSION, "terms_version": TERMS_VERSION}

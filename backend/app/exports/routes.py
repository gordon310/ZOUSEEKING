"""Owner-scoped CSV exports backed by the database usage ledger."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ..auth import AuthUser, require_user
from ..billing.entitlements import plan_for_tier
from ..db import get_pool


UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+08:00")
CSV_COLUMNS = (
    "query_key", "title", "prefecture", "city", "ward", "asset_type",
    "year", "month", "query_status", "publish_month", "summary",
)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_ids: Optional[list[UUID]] = Field(default=None, max_length=1000)


class ExportStore(Protocol):
    async def create_export(self, user: AuthUser, query_ids: Optional[list[UUID]]) -> dict[str, Any]: ...
    async def list_exports(self, user: AuthUser) -> list[dict[str, Any]]: ...
    async def download_export(self, user: AuthUser, export_id: UUID) -> bytes: ...


class ExportForbidden(Exception):
    pass


class ExportQuotaExceeded(Exception):
    pass


class EmptyExport(Exception):
    pass


def build_csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _metadata(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "status": str(row["status"]),
        "row_count": int(row["row_count"]),
        "created_at": _iso(row["created_at"]),
        "download_url": f"/api/exports/{row['id']}",
    }


class DbExportStore:
    async def _owned_rows(self, conn: asyncpg.Connection, user_id: UUID, query_ids: Optional[list[UUID]], row_cap: int) -> list[Any]:
        if query_ids is not None:
            unique_ids = list(dict.fromkeys(query_ids))
            rows = await conn.fetch(
                """
                select q.id, q.query_key, q.prefecture, q.city, q.ward, q.asset_type,
                       q.year, q.month, q.status as query_status, pr.title,
                       pr.publish_month, pr.summary
                from public.queries q
                join public.property_reports pr on pr.query_id = q.id
                where q.owner_user_id=$1 and q.id = any($2::uuid[])
                  and coalesce(pr.data_class, '') <> 'synthetic_fixture'
                order by q.created_at desc
                """,
                user_id, unique_ids,
            )
            if len(rows) != len(unique_ids):
                raise ExportForbidden("one or more requested reports are not owned by this user")
            return list(rows)
        return list(await conn.fetch(
            """
            select q.id, q.query_key, q.prefecture, q.city, q.ward, q.asset_type,
                   q.year, q.month, q.status as query_status, pr.title,
                   pr.publish_month, pr.summary
            from public.queries q
            join public.property_reports pr on pr.query_id = q.id
            where q.owner_user_id=$1
              and coalesce(pr.data_class, '') <> 'synthetic_fixture'
            order by q.created_at desc
            limit $2
            """,
            user_id, row_cap + 1,
        ))

    @staticmethod
    def _csv_rows(rows: list[Any]) -> list[dict[str, Any]]:
        result = []
        for row in rows:
            summary = row["summary"]
            result.append({
                "query_key": row["query_key"], "title": row["title"],
                "prefecture": row["prefecture"], "city": row["city"],
                "ward": row["ward"], "asset_type": row["asset_type"],
                "year": row["year"], "month": row["month"],
                "query_status": row["query_status"],
                "publish_month": row["publish_month"],
                "summary": summary if isinstance(summary, str) else json.dumps(summary or {}, ensure_ascii=False, sort_keys=True),
            })
        return result

    async def _export_limit(self, conn: asyncpg.Connection, user_id: UUID) -> int:
        profile = await conn.fetchrow(
            "select membership_tier, audience from public.user_profiles where user_id=$1", user_id
        )
        tier = (profile["membership_tier"] if profile else None) or "free"
        audience = (profile["audience"] if profile else None) or "c"
        plan_code = plan_for_tier(tier, audience)
        plan = await conn.fetchrow(
            "select plan_code, export_rows_monthly from public.pricing_plans where plan_code=$1 and active=true",
            plan_code,
        )
        if not plan:
            return 0
        entitlement = await conn.fetchrow(
            """
            select limit_units from public.plan_entitlements
            where plan_code=$1 and metric='export_row' and period='month' and active=true
            order by effective_from desc, created_at desc limit 1
            """,
            plan["plan_code"],
        )
        if entitlement is not None:
            return max(0, int(entitlement["limit_units"]))
        legacy = plan["export_rows_monthly"]
        return max(0, int(legacy)) if legacy is not None else 0

    async def create_export(self, user: AuthUser, query_ids: Optional[list[UUID]]) -> dict[str, Any]:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                limit = await self._export_limit(conn, user.user_id)
                rows = await self._owned_rows(conn, user.user_id, query_ids, limit)
                if not rows:
                    raise EmptyExport("no owned reports are available for export")
                csv_content = build_csv(self._csv_rows(rows))
                row_count = len(rows)
                if row_count > limit:
                    raise ExportQuotaExceeded("export row quota exceeded")
                export_id = uuid4()
                period_key = datetime.now(timezone.utc).astimezone(UTC_PLUS_8).strftime("%Y-%m")
                scope_key = f"user:{user.user_id}"
                await conn.execute(
                    """
                    insert into public.usage_quotas(scope_key, usage_kind, period_key, limit_units)
                    values($1, 'export_row', $2, $3)
                    on conflict(scope_key, usage_kind, period_key) do nothing
                    """, scope_key, period_key, limit,
                )
                quota = await conn.fetchrow(
                    """
                    select consumed_units, reserved_units, limit_units
                    from public.usage_quotas
                    where scope_key=$1 and usage_kind='export_row' and period_key=$2 for update
                    """, scope_key, period_key,
                )
                if quota is None or int(quota["limit_units"]) < limit or int(quota["consumed_units"]) + int(quota["reserved_units"]) + row_count > int(quota["limit_units"]):
                    raise ExportQuotaExceeded("export row quota exceeded")
                fingerprint = f"export:{export_id}:{row_count}"
                await conn.execute(
                    """
                    insert into public.exports(id, owner_user_id, status, row_count, csv_content)
                    values($1, $2, 'completed', $3, $4)
                    """, export_id, user.user_id, row_count, csv_content,
                )
                await conn.execute(
                    """
                    insert into public.usage_events(scope_key, usage_kind, operation, units, period_key, idempotency_key, fingerprint, actor_user_id)
                    values($1, 'export_row', 'consume', $2, $3, $4, $5, $6)
                    """, scope_key, row_count, period_key, f"export:{export_id}", fingerprint, user.user_id,
                )
                await conn.execute(
                    """
                    insert into public.usage_idempotency(scope_key, usage_kind, operation, idempotency_key, fingerprint)
                    values($1, 'export_row', 'consume', $2, $3)
                    """, scope_key, f"export:{export_id}", fingerprint,
                )
                await conn.execute(
                    """
                    update public.usage_quotas set consumed_units=consumed_units+$1
                    where scope_key=$2 and usage_kind='export_row' and period_key=$3
                    """, row_count, scope_key, period_key,
                )
                created = await conn.fetchrow(
                    "select id, status, row_count, created_at from public.exports where id=$1", export_id
                )
                return _metadata(created)

    async def list_exports(self, user: AuthUser) -> list[dict[str, Any]]:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                "select id, status, row_count, created_at from public.exports where owner_user_id=$1 order by created_at desc limit 100",
                user.user_id,
            )
        return [_metadata(row) for row in rows]

    async def download_export(self, user: AuthUser, export_id: UUID) -> bytes:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "select csv_content from public.exports where id=$1 and owner_user_id=$2", export_id, user.user_id
            )
        if not row:
            raise HTTPException(status_code=404, detail="export not found")
        return bytes(row["csv_content"])


def get_export_store() -> ExportStore:
    return DbExportStore()


router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.post("", status_code=201)
async def create_export(
    request: ExportRequest,
    user: AuthUser = Depends(require_user),
    store: ExportStore = Depends(get_export_store),
) -> dict[str, Any]:
    try:
        return await store.create_export(user, request.query_ids)
    except ExportForbidden as exc:
        raise HTTPException(status_code=403, detail="requested report is not available to this user") from exc
    except EmptyExport as exc:
        raise HTTPException(status_code=422, detail="no owned reports are available for export") from exc
    except ExportQuotaExceeded:
        return _quota_error()
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError) as exc:
        raise HTTPException(status_code=503, detail="export service is not configured") from exc


def _quota_error() -> Any:
    return JSONResponse(status_code=429, content={"error": {"code": "quota_exceeded", "message": "export row quota exceeded"}})


@router.get("")
async def list_exports(
    user: AuthUser = Depends(require_user),
    store: ExportStore = Depends(get_export_store),
) -> dict[str, Any]:
    try:
        return {"exports": await store.list_exports(user)}
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError) as exc:
        raise HTTPException(status_code=503, detail="export service is not configured") from exc


@router.get("/{export_id}")
async def download_export(
    export_id: UUID,
    user: AuthUser = Depends(require_user),
    store: ExportStore = Depends(get_export_store),
) -> Response:
    try:
        content = await store.download_export(user, export_id)
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError) as exc:
        raise HTTPException(status_code=503, detail="export service is not configured") from exc
    return Response(content=content, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="export-{export_id}.csv"'})

"""Owner-scoped statistical analysis backed by canonical numeric report fields."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..auth import AuthUser, require_user
from ..billing.entitlements import plan_for_tier
from ..db import get_pool


UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+08:00")
MIN_SAMPLE_COUNT = 2
ALLOWED_DATA_CLASSES = frozenset({"verified_observation", "scraped_aggregate", "modeled_estimate"})


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(default="sale", pattern="^(sale|rent|ratio)$")
    layout: str = Field(min_length=1, max_length=40)
    keyword: str = Field(default="", max_length=120)
    prefecture: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=80)
    ward: str = Field(default="", max_length=80)
    asset_type: str = Field(default="", max_length=80)
    from_month: Optional[str] = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    to_month: Optional[str] = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @model_validator(mode="after")
    def validate_month_range(self) -> "AnalysisRequest":
        if self.from_month and self.to_month and self.from_month > self.to_month:
            raise ValueError("from_month must not be after to_month")
        return self


class AnalysisQuotaExceeded(Exception):
    pass


class AnalysisServiceUnavailable(Exception):
    pass


class AnalysisStore(Protocol):
    async def analyze(self, user: AuthUser, request: AnalysisRequest) -> dict[str, Any]: ...


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _number(value: Any) -> Optional[float]:
    # Analytics must consume canonical numeric fields, never presentation strings.
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    number = float(value)
    return number if number > 0 else None


def _row_value(row: dict[str, Any], metric: str, layout: str) -> Optional[float]:
    sale = {item.get("layout"): item for item in (_json(row.get("sale"), []) or []) if isinstance(item, dict)}
    rental = {item.get("layout"): item for item in (_json(row.get("rental"), []) or []) if isinstance(item, dict)}
    if metric == "sale":
        return _number((sale.get(layout) or {}).get("amount_yen"))
    if metric == "rent":
        return _number((rental.get(layout) or {}).get("amount_yen"))
    rent = _number((rental.get(layout) or {}).get("amount_yen"))
    price = _number((sale.get(layout) or {}).get("amount_yen"))
    return rent * 12 / price * 100 if rent is not None and price is not None else None


def aggregate_rows(rows: list[dict[str, Any]], request: AnalysisRequest) -> dict[str, Any]:
    buckets: dict[str, list[float]] = {}
    source_classes: set[str] = set()
    source_map: dict[tuple[str, str], dict[str, Any]] = {}
    sample_count = 0

    for row in rows:
        if str(row.get("data_class") or "") not in ALLOWED_DATA_CLASSES:
            continue
        value = _row_value(row, request.metric, request.layout)
        if value is None:
            continue
        month = f"{int(row['year']):04d}-{int(row['month']):02d}"
        buckets.setdefault(month, []).append(value)
        sample_count += 1
        data_class = str(row["data_class"])
        source_classes.add(data_class)
        for source in _json(row.get("data_sources"), []) or []:
            if not isinstance(source, dict):
                continue
            name = str(source.get("name") or "").strip()
            url = str(source.get("url") or "").strip()
            if name or url:
                source_map[(name, url)] = {
                    "name": name,
                    "url": url,
                    "data_class": str(source.get("data_class") or data_class),
                    "period": source.get("period"),
                }

    points = [
        {"month": month, "value": sum(values) / len(values), "sample_count": len(values)}
        for month, values in sorted(buckets.items())
    ]
    result: dict[str, Any] = {
        "status": "ok" if sample_count >= MIN_SAMPLE_COUNT else "insufficient_sample",
        "metric": request.metric,
        "layout": request.layout,
        "unit": "JPY" if request.metric == "sale" else "JPY/month" if request.metric == "rent" else "percent",
        "aggregation": "arithmetic_mean",
        "sample_count": sample_count,
        "period": {"from": points[0]["month"] if points else None, "to": points[-1]["month"] if points else None},
        "points": points if sample_count >= MIN_SAMPLE_COUNT else [],
        "source_class": sorted(source_classes),
        "sources": sorted(source_map.values(), key=lambda item: (item["name"], item["url"])),
    }
    if result["status"] == "insufficient_sample":
        result["message"] = "样本不足，无法生成统计分析。"
    return result


class DbAnalysisStore:
    async def _scope_and_limit(self, conn: asyncpg.Connection, user_id: UUID) -> tuple[str, int]:
        profile = await conn.fetchrow(
            "select membership_tier, audience from public.user_profiles where user_id=$1", user_id
        )
        tier = (profile["membership_tier"] if profile else None) or "free"
        audience = (profile["audience"] if profile else None) or "c"
        org = await conn.fetchrow(
            """
            select om.organization_id
            from public.organization_members om
            join public.subscriptions s on s.organization_id=om.organization_id
            where om.user_id=$1 and om.status='active'
              and s.product_code='b_data_pro_monthly'
              and s.status in ('active','trialing')
              and (s.current_period_end is null or s.current_period_end > now())
            order by om.created_at asc limit 1
            """,
            user_id,
        )
        if org:
            scope_key = f"org:{org['organization_id']}"
            tier, audience = "b_data_pro", "b"
        else:
            scope_key = f"user:{user_id}"
        plan_code = plan_for_tier(tier, audience)
        entitlement = await conn.fetchrow(
            """
            select limit_units from public.plan_entitlements
            where plan_code=$1 and metric='stats_query' and period='month' and active=true
            order by effective_from desc nulls last, created_at desc limit 1
            """,
            plan_code,
        )
        if entitlement is None:
            raise AnalysisServiceUnavailable("stats entitlement is not configured")
        return scope_key, max(0, int(entitlement["limit_units"]))

    async def _owned_rows(self, conn: asyncpg.Connection, user_id: UUID, request: AnalysisRequest) -> list[dict[str, Any]]:
        clauses = [
            "(q.owner_user_id=$1 or pr.owner_user_id=$1)",
            "q.status='completed'",
            "coalesce(pr.data_class::text, '') = any($2::text[])",
        ]
        args: list[Any] = [user_id, list(ALLOWED_DATA_CLASSES)]
        for value, column in ((request.prefecture, "q.prefecture"), (request.city, "q.city"), (request.ward, "q.ward"), (request.asset_type, "q.asset_type")):
            if value:
                args.append(value)
                clauses.append(f"{column}=$%d" % len(args))
        if request.keyword:
            args.append(f"%{request.keyword}%")
            clauses.append("(q.prefecture || q.city || q.ward || q.asset_type || pr.title) ilike $%d" % len(args))
        if request.from_month:
            args.extend([int(request.from_month[:4]), int(request.from_month[5:])])
            clauses.append("(q.year, q.month) >= ($%d, $%d)" % (len(args) - 1, len(args)))
        if request.to_month:
            args.extend([int(request.to_month[:4]), int(request.to_month[5:])])
            clauses.append("(q.year, q.month) <= ($%d, $%d)" % (len(args) - 1, len(args)))
        query = f"""
            select q.year, q.month, q.prefecture, q.city, q.ward, q.asset_type,
                   pr.title, pr.data_class::text as data_class, pr.rental,
                   pr.sale, pr.data_sources
            from public.queries q
            join public.property_reports pr on pr.query_id=q.id
            where {' and '.join(clauses)}
            order by q.year, q.month, q.created_at
        """
        return [dict(row) for row in await conn.fetch(query, *args)]

    async def _meter(self, conn: asyncpg.Connection, scope_key: str, limit: int, user_id: UUID) -> dict[str, Any]:
        period_key = datetime.now(timezone.utc).astimezone(UTC_PLUS_8).strftime("%Y-%m")
        await conn.execute(
            """
            insert into public.usage_quotas(scope_key, usage_kind, period_key, limit_units)
            values($1, 'stats_query', $2, $3)
            on conflict(scope_key, usage_kind, period_key) do nothing
            """,
            scope_key, period_key, limit,
        )
        quota = await conn.fetchrow(
            """
            select consumed_units, reserved_units, limit_units
            from public.usage_quotas
            where scope_key=$1 and usage_kind='stats_query' and period_key=$2 for update
            """,
            scope_key, period_key,
        )
        if quota is None or int(quota["limit_units"]) < int(quota["consumed_units"]) + int(quota["reserved_units"]) + 1:
            raise AnalysisQuotaExceeded()
        event_id = uuid4()
        fingerprint = "stats:" + hashlib.sha256(f"{scope_key}:{user_id}:{event_id}".encode()).hexdigest()
        await conn.execute(
            """
            insert into public.usage_events(id, scope_key, usage_kind, operation, units, period_key, idempotency_key, fingerprint, actor_user_id)
            values($1,$2,'stats_query','consume',1,$3,$4,$5,$6)
            """,
            event_id, scope_key, period_key, str(event_id), fingerprint, user_id,
        )
        await conn.execute(
            """
            insert into public.usage_idempotency(scope_key, usage_kind, operation, idempotency_key, fingerprint)
            values($1, 'stats_query', 'consume', $2, $3)
            """,
            scope_key, str(event_id), fingerprint,
        )
        await conn.execute(
            "update public.usage_quotas set consumed_units=consumed_units+1 where scope_key=$1 and usage_kind='stats_query' and period_key=$2",
            scope_key, period_key,
        )
        used = int(quota["consumed_units"]) + 1
        return {"used": used, "limit": int(quota["limit_units"]), "remaining": int(quota["limit_units"]) - used, "period": period_key}

    async def _quota_snapshot(self, conn: asyncpg.Connection, scope_key: str, limit: int) -> dict[str, Any]:
        period_key = datetime.now(timezone.utc).astimezone(UTC_PLUS_8).strftime("%Y-%m")
        quota = await conn.fetchrow(
            """
            select consumed_units, limit_units from public.usage_quotas
            where scope_key=$1 and usage_kind='stats_query' and period_key=$2
            """,
            scope_key, period_key,
        )
        used = int(quota["consumed_units"]) if quota else 0
        actual_limit = int(quota["limit_units"]) if quota else limit
        return {"used": used, "limit": actual_limit, "remaining": max(0, actual_limit - used), "period": period_key}

    async def analyze(self, user: AuthUser, request: AnalysisRequest) -> dict[str, Any]:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                rows = await self._owned_rows(conn, user.user_id, request)
                result = aggregate_rows(rows, request)
                scope_key, limit = await self._scope_and_limit(conn, user.user_id)
                if result["status"] != "ok":
                    result["quota"] = await self._quota_snapshot(conn, scope_key, limit)
                    return result
                result["quota"] = await self._meter(conn, scope_key, limit, user.user_id)
                return result


def get_analysis_store() -> AnalysisStore:
    return DbAnalysisStore()


router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("")
async def create_analysis(
    request: AnalysisRequest,
    user: AuthUser = Depends(require_user),
    store: AnalysisStore = Depends(get_analysis_store),
) -> dict[str, Any]:
    try:
        return await store.analyze(user, request)
    except AnalysisQuotaExceeded:
        return JSONResponse(status_code=429, content={"error": {"code": "quota_exceeded", "message": "analysis quota exceeded"}})
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError, AnalysisServiceUnavailable):
        raise HTTPException(status_code=503, detail="analysis service is not configured")

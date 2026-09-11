from __future__ import annotations

import os
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .db import close, connect, get_pool, init_schema
from .auth import AuthUser, require_user
from .intake import storage as intake_storage
from .intake.market_engine import build_sale_report, load_snapshots, match_snapshot
from .intake.repository import IntakeRepository
from .jphouse_service import (
    fallback_sources,
    placeholder_xhs,
    query_key,
    query_title,
)
from .models import JobResponse, QueryRequest, QueryResponse
from .routes.health import router as health_router
from .routes.intake import cleanup_expired_sessions, router as intake_router
from .routes.renovation import router as renovation_router
from .routes.privacy import router as privacy_router
from .recognition.routes import router as recognition_router
from .release_scope import request_allowed
from .admin.routes import router as admin_router
from .billing.routes import router as billing_router
from .usage.routes import router as usage_router


ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:8790,http://localhost:8790,https://gordon310.github.io",
    ).split(",")
    if origin.strip()
]
SCHEMA_INIT_ENVIRONMENTS = {"local", "development", "test"}


def should_init_schema() -> bool:
    requested = os.getenv("INIT_SCHEMA", "false").strip().lower() == "true"
    environment = os.getenv("ENVIRONMENT", "").strip().lower()
    return requested and environment in SCHEMA_INIT_ENVIRONMENTS


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    if should_init_schema():
        await init_schema()
    await cleanup_expired_sessions(IntakeRepository(get_pool()), intake_storage)
    yield
    await close()


app = FastAPI(title="ZOU SEEKING HOUSE JPHOUSE API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def enforce_release_scope(request, call_next):
    if not request_allowed(request.method, request.url.path):
        return JSONResponse(
            status_code=404,
            content={"detail": "operation unavailable in current release phase"},
        )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(intake_router)
app.include_router(renovation_router)
app.include_router(billing_router)
app.include_router(usage_router)
app.include_router(admin_router)
app.include_router(privacy_router)
app.include_router(recognition_router)


@app.get("/internal/provenance/diagnostics")
async def provenance_diagnostics(x_internal_diagnostics_token: Optional[str] = Header(default=None)) -> dict[str, str]:
    """Return safe source status metadata; never return raw documents or secrets."""

    expected = os.getenv("INTERNAL_DIAGNOSTICS_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=404, detail="not found")
    if x_internal_diagnostics_token != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    return {
        "status": os.getenv("PROVENANCE_STATUS", "not_configured"),
        "last_success_at": os.getenv("PROVENANCE_LAST_SUCCESS_AT", ""),
        "parser_version": os.getenv("PROVENANCE_PARSER_VERSION", "unparsed"),
    }


UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+08:00")


def _current_month_key(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(UTC_PLUS_8).strftime("%Y-%m")


async def _has_report_unlock(conn: Any, user_id: Any, report_key: str) -> bool:
    """Return whether this exact report is paid or covered by C Plus quota."""
    row = await conn.fetchrow(
        """
        select 1
        from public.payment_orders
        where owner_user_id=$1 and product_code='risk_report_single'
          and subject_id=$2 and status='paid'
        union all
        select 1
        from public.subscriptions s
        join public.usage_quotas uq
          on uq.scope_key = 'user:' || s.user_id::text
         and uq.usage_kind = 'report'
         and uq.period_key = $3
        where s.user_id=$1 and s.product_code='c_plus_monthly'
          and s.status in ('active', 'trialing')
          and (s.current_period_end is null or s.current_period_end > now())
          and uq.consumed_units + uq.reserved_units < uq.limit_units
        union all
        select 1
        from public.usage_events ue
        where ue.scope_key = 'user:' || $1::text
          and ue.usage_kind = 'report'
          and ue.operation = 'consume'
          and ue.fingerprint = 'c-plus-report:' || $2
        limit 1
        """,
        user_id,
        report_key,
        _current_month_key(),
    )
    return row is not None


async def _consume_c_plus_report_quota(user_id: Any, report_key: str) -> bool:
    """Consume one C Plus report slot once, keyed by the generated report."""
    period_key = _current_month_key()
    scope_key = f"user:{user_id}"
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            sub = await conn.fetchrow(
                "select 1 from public.subscriptions"
                " where user_id=$1 and product_code='c_plus_monthly'"
                "   and status in ('active', 'trialing')"
                "   and (current_period_end is null or current_period_end > now())"
                " limit 1",
                user_id,
            )
            if sub is None:
                return False
            await conn.execute(
                "insert into public.usage_quotas"
                " (scope_key, usage_kind, period_key, limit_units)"
                " values ($1, 'report', $2, 12)"
                " on conflict (scope_key, usage_kind, period_key) do nothing",
                scope_key, period_key,
            )
            fingerprint = f"c-plus-report:{report_key}"
            event = await conn.fetchrow(
                "insert into public.usage_events"
                " (scope_key, usage_kind, operation, units, period_key, idempotency_key, fingerprint, actor_user_id)"
                " values ($1, 'report', 'consume', 1, $2, $3, $3, $4)"
                " on conflict (scope_key, usage_kind, operation, fingerprint) do nothing"
                " returning id",
                scope_key, period_key, fingerprint, user_id,
            )
            if event is None:
                return True
            updated = await conn.execute(
                "update public.usage_quotas set consumed_units=consumed_units+1"
                " where scope_key=$1 and usage_kind='report' and period_key=$2"
                " and consumed_units + reserved_units < limit_units",
                scope_key, period_key,
            )
            if not updated or int(updated.split()[-1]) != 1:
                raise RuntimeError("subscription report quota exhausted")
            return True


def row_to_report(row: Any) -> dict[str, Any]:
    def json_value(name: str, fallback: Any) -> Any:
        value = row[name]
        if value is None:
            return fallback
        if isinstance(value, str):
            return json.loads(value)
        return value

    return {
        "slug": row["slug"],
        "title": row["title"],
        "publish_month": row["publish_month"],
        "markdown": row["markdown"],
        "xhs_content": row["xhs_content"],
        "rental": json_value("rental", []),
        "sale": json_value("sale", []),
        "summary": json_value("summary", {}),
        "images": json_value("images", []),
        "data_sources": json_value("data_sources", []),
        "raw_record": json_value("raw_record", {}),
    }


async def save_report(query_id: str, owner_user_id: str, report: dict[str, Any]) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into property_reports
              (query_id, owner_user_id, query_key, slug, title, publish_month, markdown, xhs_content, rental, sale, summary, images, data_sources, raw_record)
            values
              ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14::jsonb)
            on conflict (query_id) do update set
              query_key = excluded.query_key,
              slug = excluded.slug,
              title = excluded.title,
              publish_month = excluded.publish_month,
              markdown = excluded.markdown,
              xhs_content = excluded.xhs_content,
              rental = excluded.rental,
              sale = excluded.sale,
              summary = excluded.summary,
              images = excluded.images,
              data_sources = excluded.data_sources,
              raw_record = excluded.raw_record,
              updated_at = now()
            """,
            query_id,
            owner_user_id,
            report["query_key"],
            report["slug"],
            report["title"],
            report["publish_month"],
            report["markdown"],
            report["xhs_content"],
            json.dumps(report["rental"], ensure_ascii=False),
            json.dumps(report["sale"], ensure_ascii=False),
            json.dumps(report["summary"], ensure_ascii=False),
            json.dumps(report["images"], ensure_ascii=False),
            json.dumps(report["data_sources"], ensure_ascii=False),
            json.dumps(report["raw_record"], ensure_ascii=False),
        )


async def run_generation_job(job_id: str, query_id: str, owner_user_id: str, request: QueryRequest) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update generation_jobs set status='running', progress=20, current_step='检查本地历史数据', updated_at=now() where id=$1",
            job_id,
        )
    try:
        snapshot = match_snapshot(
            load_snapshots(),
            request.prefecture,
            request.ward,
            request.asset_type,
            request.city,
        )
        if snapshot:
            report = build_sale_report(snapshot, request.model_dump())
        else:
            title = query_title(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month)
            report = {
                "slug": query_key(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month).replace("::", "_"),
                "title": title,
                "publish_month": f"{request.year}年{request.month}月",
                "markdown": f"# {title}\n\n数据生成任务已创建，等待采集器补全。",
                "xhs_content": placeholder_xhs(
                    request.prefecture,
                    request.city,
                    request.ward,
                    request.asset_type,
                    request.year,
                    request.month,
                ),
                "rental": [],
                "sale": [],
                "summary": {"title": "总而言之", "line": "待生成", "note": "等待 JPHOUSE 采集器补全。"},
                "images": [],
                "data_sources": fallback_sources(request.prefecture, request.city, request.ward),
                "raw_record": {"status": "queued"},
            }
        async with get_pool().acquire() as conn:
            query_key_value = await conn.fetchval(
                "select query_key from queries where id=$1",
                query_id,
            )
        if query_key_value:
            report["query_key"] = query_key_value
        else:
            report.setdefault(
                "query_key",
                query_key(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month),
            )
        async with get_pool().acquire() as conn:
            await conn.execute(
                "update generation_jobs set progress=75, current_step='保存数据和索引', updated_at=now() where id=$1",
                job_id,
            )
        await save_report(query_id, owner_user_id, report)
        await _consume_c_plus_report_quota(owner_user_id, report["query_key"])
        async with get_pool().acquire() as conn:
            await conn.execute("update queries set status='completed', updated_at=now() where id=$1", query_id)
            await conn.execute(
                "update generation_jobs set status='completed', progress=100, current_step='完成', updated_at=now() where id=$1",
                job_id,
            )
    except Exception as exc:
        async with get_pool().acquire() as conn:
            await conn.execute("update queries set status='failed', updated_at=now() where id=$1", query_id)
            await conn.execute(
                "update generation_jobs set status='failed', progress=100, current_step='失败', error_message=$2, updated_at=now() where id=$1",
                job_id,
                str(exc),
            )


@app.post("/api/query", response_model=QueryResponse)
async def query_report(
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_user),
) -> QueryResponse:
    base_key = query_key(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month)
    key = f"{user.user_id}::{base_key}"
    title = query_title(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month)
    async with get_pool().acquire() as conn:
        existing = await conn.fetchrow(
            """
            select pr.*
            from queries q
            join property_reports pr on pr.query_id = q.id
            where q.query_key = $1
            """,
            key,
        )
        if existing:
            return QueryResponse(query_key=key, status="completed", cached=True, title=title, report=row_to_report(existing), message="命中历史数据")

        query_id = await conn.fetchval(
            """
            insert into queries(query_key, owner_user_id, prefecture, city, ward, asset_type, year, month, status)
            values($1, $2, $3, $4, $5, $6, $7, $8, 'pending')
            on conflict(query_key) do update set updated_at=now()
            returning id
            """,
            key,
            user.user_id,
            request.prefecture,
            request.city,
            request.ward or "",
            request.asset_type,
            request.year,
            request.month,
        )
        job_id = await conn.fetchval(
            """
            insert into generation_jobs(query_id, status, progress, current_step)
            values($1, 'pending', 5, '任务已创建')
            returning id
            """,
            query_id,
        )
    background_tasks.add_task(run_generation_job, str(job_id), str(query_id), user.user_id, request)
    return QueryResponse(query_key=key, status="pending", cached=False, title=title, job_id=str(job_id), message="已创建生成任务")


@app.post("/api/jobs/{query_id}/run", response_model=JobResponse, status_code=202)
async def run_legacy_job(
    query_id: str,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_user),
) -> JobResponse:
    """Start/restart the report job of a query (by query_id) through the authenticated API boundary."""

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            select q.id as query_id, q.prefecture, q.city, q.ward, q.asset_type, q.year, q.month,
                   gj.id as job_id, gj.status, gj.progress, gj.current_step, gj.error_message
            from queries q
            left join generation_jobs gj on gj.query_id = q.id
            where q.id = $1 and q.owner_user_id = $2
            order by gj.created_at desc
            limit 1
            """,
            query_id,
            user.user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="query not found")

        job_id = row["job_id"]
        status = row["status"]
        progress = row["progress"]
        current_step = row["current_step"]
        error_message = row["error_message"]
        if job_id is None:
            job_id = await conn.fetchval(
                """
                insert into generation_jobs (query_id, status, progress, current_step)
                values ($1, 'pending', 5, '任务已创建')
                returning id
                """,
                row["query_id"],
            )
            status = "pending"
            progress = 5
            current_step = "任务已创建"
            error_message = None
        if row["status"] in {"completed", "running"}:
            return JobResponse(
                job_id=str(job_id),
                status=status,
                progress=progress,
                current_step=current_step,
                error_message=error_message,
            )

        claimed = await conn.fetchrow(
            """
            update generation_jobs gj
            set status='running', progress=20, current_step='检查本地历史数据', error_message=null, updated_at=now()
            from queries q
            where gj.id=$1
              and q.id=gj.query_id
              and q.owner_user_id=$2
              and gj.status in ('pending', 'failed')
            returning gj.id, gj.query_id, gj.progress, gj.current_step, gj.error_message,
                      q.prefecture, q.city, q.ward, q.asset_type, q.year, q.month
            """,
            job_id,
            user.user_id,
        )
        if not claimed:
            raise HTTPException(status_code=409, detail="job is already being handled")
        await conn.execute(
            "update queries set status='running', updated_at=now() where id=$1 and owner_user_id=$2",
            row["query_id"],
            user.user_id,
        )

    request = QueryRequest(
        prefecture=row["prefecture"],
        city=row["city"],
        ward=row["ward"] or "",
        asset_type=row["asset_type"],
        year=row["year"],
        month=row["month"],
        username=user.username,
    )
    background_tasks.add_task(
        run_generation_job,
        str(job_id),
        str(row["query_id"]),
        str(user.user_id),
        request,
    )
    return JobResponse(
        job_id=str(job_id),
        status="running",
        progress=20,
        current_step="检查本地历史数据",
        error_message=None,
    )


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, user: AuthUser = Depends(require_user)) -> JobResponse:
    async with get_pool().acquire() as conn:
        job = await conn.fetchrow(
            """
            select gj.*
            from generation_jobs gj
            join queries q on q.id = gj.query_id
            where gj.id=$1 and q.owner_user_id=$2
            """,
            job_id,
            user.user_id,
        )
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        report = None
        if job["status"] == "completed":
            row = await conn.fetchrow(
                """
                select pr.*
                from generation_jobs gj
                join property_reports pr on pr.query_id = gj.query_id
                join queries q on q.id = gj.query_id
                where gj.id=$1 and q.owner_user_id=$2
                """,
                job_id,
                user.user_id,
            )
            if row:
                report = row_to_report(row)
        return JobResponse(
            job_id=str(job["id"]),
            status=job["status"],
            progress=job["progress"],
            current_step=job["current_step"],
            error_message=job["error_message"],
            report=report,
        )


@app.get("/api/my/queries")
async def list_my_queries(user: AuthUser = Depends(require_user)) -> list[dict[str, Any]]:
    """Return only the authenticated user's query/job records."""

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            select q.*, coalesce(
              json_agg(
                json_build_object(
                  'id', gj.id,
                  'status', gj.status,
                  'progress', gj.progress,
                  'current_step', gj.current_step,
                  'error_message', gj.error_message,
                  'created_at', gj.created_at
                ) order by gj.created_at desc
              ) filter (where gj.id is not null), '[]'::json
            ) as generation_jobs
            from queries q
            left join generation_jobs gj on gj.query_id = q.id
            where q.owner_user_id=$1
            group by q.id
            order by q.created_at desc
            limit 100
            """,
            user.user_id,
        )
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if isinstance(item.get("generation_jobs"), str):
            item["generation_jobs"] = json.loads(item["generation_jobs"])
        result.append(item)
    return result


@app.get("/api/reports/{query_key}")
async def get_my_report(query_key: str, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            select pr.*
            from property_reports pr
            join queries q on q.id = pr.query_id
            where pr.query_key=$1 and q.owner_user_id=$2
            limit 1
            """,
            query_key,
            user.user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="report not found")
        unlocked = await _has_report_unlock(conn, user.user_id, query_key)
    if not unlocked:
        # D7/D8b: full report content is a paid deliverable (risk_report_single,
        # report-scoped unlock). A locked response carries metadata only - the
        # content fields (markdown/rental/sale/summary/...) are never sent.
        return {
            "locked": True,
            "query_key": query_key,
            "slug": row["slug"],
            "title": row["title"],
            "publish_month": row["publish_month"],
            "unlock_hint": "完整深度报告与导出为付费权益(risk_report_single)。购买后解锁本份深度报告。",
        }
    return row_to_report(row)

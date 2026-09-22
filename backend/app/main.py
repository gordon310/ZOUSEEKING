from __future__ import annotations

import os
import json
import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from urllib.parse import quote
from html import escape

from .db import close, connect, get_pool
from .auth import AuthUser, optional_user, require_user
from .intake import storage as intake_storage
from .intake.market_engine import build_sale_report, load_snapshots, match_snapshot
from .intake.repository import IntakeRepository
from .jphouse_service import (
    display_query_ward,
    fallback_sources,
    placeholder_xhs,
    query_key,
    query_title,
)
from .models import JobResponse, QueryRequest, QueryResponse
from .report_worker import enqueue_report_outbox
from .routes.health import router as health_router
from .routes.intake import cleanup_expired_sessions, router as intake_router
from .routes.renovation import router as renovation_router
from .routes.privacy import router as privacy_router
from .recognition.routes import router as recognition_router
from .release_scope import request_allowed
from .admin.routes import router as admin_router
from .billing.routes import router as billing_router
from .usage.routes import router as usage_router
from .member.routes import router as member_router
from .exports.routes import router as exports_router
from .analysis.routes import router as analysis_router
from .region_stats_routes import router as region_stats_router
from .org.routes import router as org_router
from .service_routes import router as service_router
from .usage.ledger import QuotaExceeded
from .usage.quota import consume_current_entitlement


ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:8790,http://localhost:8790,https://gordon310.github.io",
    ).split(",")
    if origin.strip()
]
MARKET_SOURCE_CACHE_TTL_SECONDS = 60.0
_market_source_cache: tuple[str, float] | None = None
_market_source_cache_lock: asyncio.Lock | None = None
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    await cleanup_expired_sessions(IntakeRepository(get_pool()), intake_storage)
    yield
    await close()


app = FastAPI(title="ZOU SEEKING HOUSE JPHOUSE API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def scoped_http_error(request: Request, exc: HTTPException):
    """Keep organization auth failures structured without changing legacy APIs."""
    if request.url.path.startswith("/api/org/"):
        code = {
            401: "authentication_required",
            403: "org_forbidden",
            404: "not_found",
            422: "invalid_request",
        }.get(exc.status_code, "org_unavailable")
        if isinstance(exc.detail, str):
            message = exc.detail
        elif isinstance(exc.detail, dict) and isinstance(exc.detail.get("message"), str):
            message = exc.detail["message"]
        else:
            message = {
                "not_found": "请求的资源不存在。",
                "invalid_request": "请求参数无效。",
                "org_unavailable": "机构服务暂时不可用。",
            }.get(code, "请求失败。")
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": message}})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


def _validation_summary(exc: RequestValidationError) -> str:
    fields: list[str] = []
    hidden_locations = {"body", "query", "path", "header", "cookie"}
    for item in exc.errors():
        locations = [str(part) for part in item.get("loc", ()) if str(part) not in hidden_locations]
        if locations and locations[-1] not in fields:
            fields.append(locations[-1])
    if fields:
        return f"请求参数无效，请检查字段：{'、'.join(fields)}。"
    return "请求参数无效。"


@app.exception_handler(RequestValidationError)
async def scoped_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/org/"):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": _validation_summary(exc)}},
        )
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


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
app.include_router(member_router)
app.include_router(exports_router)
app.include_router(analysis_router)
app.include_router(region_stats_router)
app.include_router(org_router)
app.include_router(service_router)
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

# These fields are the paid/deep-report payload. The public response is an
# explicit allow-list and must never derive its shape by deleting from this set.
LOCKED_REPORT_FIELDS = frozenset({
    "markdown",
    "xhs_content",
    "rental",
    "sale",
    "images",
    "raw_record",
    "risk_summary",
    "risks",
})


def report_status_for_report(*, has_snapshot: bool) -> str:
    """Map generation coverage to the canonical terminal report status."""

    return "full_report" if has_snapshot else "insufficient_data"


class ReportSourceResolutionError(RuntimeError):
    """A publishable report cannot resolve its authorized source registry row."""

    code = "market_source_unavailable"
    user_message = "市场数据源暂时不可用，请稍后重试。"

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def job_error_payload(error: Exception) -> dict[str, str]:
    """Return the only error shape allowed to cross the member API boundary."""

    if isinstance(error, ReportSourceResolutionError):
        return {"code": error.code, "message": error.user_message}
    return {"code": "report_generation_failed", "message": "报告生成失败，请稍后重试。"}


def parse_job_error(value: Any) -> dict[str, str] | None:
    if not value:
        return None
    try:
        payload = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return {"code": "report_generation_failed", "message": "报告生成失败，请稍后重试。"}
    if not isinstance(payload, dict) or not payload.get("code") or not payload.get("message"):
        return {"code": "report_generation_failed", "message": "报告生成失败，请稍后重试。"}
    return {"code": str(payload["code"]), "message": str(payload["message"])}


def namespaced_report_slug(owner_user_id: str, base_slug: str) -> str:
    """Keep the human-readable slug while making it unique per owner."""

    return f"{str(owner_user_id).strip()}_{str(base_slug).strip()}"


def cached_report_action(job_status: str | None, report_status: str | None) -> str:
    """Classify an existing report/job pair while holding the query lock."""

    if report_status == "full_report":
        return "cache"
    if report_status == "insufficient_data" and job_status in {"completed", "succeeded"}:
        return "cache"
    if job_status in {"pending", "running"}:
        return "wait"
    if job_status == "failed":
        return "requeue"
    if job_status in {"completed", "succeeded"}:
        return "requeue"
    return "wait"


async def resolve_market_source_id(conn: Any) -> str:
    """Resolve the authorized market source by its stable business key.

    The cache only stores a successful, authorized lookup. Any lookup failure is
    converted to a safe structured error for the generation job.
    """

    global _market_source_cache, _market_source_cache_lock
    now = time.monotonic()
    if _market_source_cache and now - _market_source_cache[1] < MARKET_SOURCE_CACHE_TTL_SECONDS:
        return _market_source_cache[0]
    if _market_source_cache_lock is None:
        _market_source_cache_lock = asyncio.Lock()
    async with _market_source_cache_lock:
        now = time.monotonic()
        if _market_source_cache and now - _market_source_cache[1] < MARKET_SOURCE_CACHE_TTL_SECONDS:
            return _market_source_cache[0]
        try:
            row = await conn.fetchrow(
                """
                select id
                from public.sources
                where permission_status='rights_confirmed'
                  and source_type='government_open_data'
                order by updated_at desc, created_at desc
                limit 1
                """,
            )
        except Exception as exc:
            logger.warning("market source lookup failed: %s", type(exc).__name__)
            raise ReportSourceResolutionError(
                "market_source_unavailable: authorized market source lookup failed"
            ) from None
        if not row or row["id"] is None:
            raise ReportSourceResolutionError(
                "market_source_unavailable: no rights_confirmed market source is registered"
            )
        source_id = str(row["id"])
        _market_source_cache = (source_id, time.monotonic())
        return source_id


def _row_get(row: Any, name: str, fallback: Any = None) -> Any:
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return fallback


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
    """Consume the configured report entitlement once per generated report."""
    user = AuthUser(UUID(str(user_id)), "", "")
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            profile = await conn.fetchrow(
                "select membership_tier from public.user_profiles where user_id=$1", user.user_id
            )
            if not profile or profile["membership_tier"] != "c_plus":
                return False
            await consume_current_entitlement(
                conn,
                user=user,
                metric="report",
                units=1,
                idempotency_key=f"report:{report_key}",
                fingerprint=f"report:{report_key}",
            )
            return True


def row_to_report(row: Any) -> dict[str, Any]:
    def json_value(name: str, fallback: Any) -> Any:
        value = row[name]
        if value is None:
            return fallback
        if isinstance(value, str):
            return json.loads(value)
        return value

    result = {
        "query_key": _row_get(row, "query_key"),
        "slug": row["slug"],
        "title": row["title"],
        "publish_month": row["publish_month"],
        "created_at": _row_get(row, "created_at"),
        "generated_at": _row_get(row, "created_at"),
        "report_status": _row_get(row, "report_status", "generating"),
        "markdown": row["markdown"],
        "xhs_content": row["xhs_content"],
        "rental": json_value("rental", []),
        "sale": json_value("sale", []),
        "summary": json_value("summary", {}),
        "images": json_value("images", []),
        "data_sources": json_value("data_sources", []),
        "raw_record": json_value("raw_record", {}),
        "unlocked": True,
    }
    result.update({
        "data_class": _row_get(row, "data_class", "synthetic_fixture"),
        "source_url": next((item.get("url") for item in result["data_sources"] if isinstance(item, dict) and item.get("url")), "fixture://report-source-missing"),
        "retrieved_at": _row_get(row, "observed_at", _row_get(row, "created_at")),
        "source_period": _row_get(row, "source_period", result["publish_month"]),
        "transformation_version": _row_get(row, "transformation_version", "report-v1"),
        "rights_status": "rights_confirmed" if _row_get(row, "data_class") else "not_applicable",
        "rights_confirmed": "yes" if _row_get(row, "data_class") else "not_applicable",
        "sample_size": len(result["sale"]), "aggregation_method": "source_report",
        "missing_value_policy": "not_applicable_to_source_report",
        "limitations": _row_get(row, "limitations", "Source report limitations are unavailable."), "unit": "JPY",
    })
    return result


def public_report_from_row(row: Any, query_key: str) -> dict[str, Any]:
    """Return only the report fields intentionally available before purchase.

    Keep this allow-list separate from ``row_to_report``: a locked response must
    not inherit new deep-report columns by accident when the stored report grows.
    """

    def json_value(name: str, fallback: Any) -> Any:
        value = _row_get(row, name, fallback)
        if value is None:
            return fallback
        if isinstance(value, str):
            return json.loads(value)
        return value

    result: dict[str, Any] = {
        "locked": True,
        "unlocked": False,
        "query_key": query_key,
        "slug": row["slug"],
        "title": row["title"],
        "publish_month": row["publish_month"],
        "generated_at": _row_get(row, "created_at"),
        "report_status": _row_get(row, "report_status", "generating"),
        "summary": json_value("summary", {}),
        "data_sources": json_value("data_sources", []),
        "unlock_hint": "完整深度报告与导出为付费权益(risk_report_single)。购买后解锁本份深度报告。",
    }
    created_at = _row_get(row, "created_at")
    if created_at is not None:
        result["created_at"] = created_at
    for name in ("address", "location", "source", "source_label"):
        value = _row_get(row, name)
        if value is not None:
            result[name] = value
    result.update({
        "data_class": _row_get(row, "data_class", "synthetic_fixture"),
        "source_url": next((item.get("url") for item in result["data_sources"] if isinstance(item, dict) and item.get("url")), "fixture://report-source-missing"),
        "retrieved_at": _row_get(row, "observed_at", _row_get(row, "created_at")),
        "source_period": _row_get(row, "source_period", result["publish_month"]),
        "transformation_version": _row_get(row, "transformation_version", "report-v1"),
        "rights_status": "rights_confirmed" if _row_get(row, "data_class") else "not_applicable",
        "rights_confirmed": "yes" if _row_get(row, "data_class") else "not_applicable",
        "sample_size": 0, "aggregation_method": "source_report",
        "missing_value_policy": "not_applicable_to_locked_metadata",
        "limitations": _row_get(row, "limitations", "Source report limitations are unavailable."), "unit": "JPY",
    })
    return result


def _report_json_value(row: Any, name: str, fallback: Any) -> Any:
    value = _row_get(row, name, fallback)
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _html_text(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _html_list(items: Any, empty: str = "暂无记录") -> str:
    values = items if isinstance(items, list) else []
    if not values:
        return f"<p>{_html_text(empty)}</p>"
    return "<ul>" + "".join(f"<li>{_html_text(item)}</li>" for item in values) + "</ul>"


def _download_filename(row: Any) -> str:
    parts = [
        _row_get(row, "prefecture"),
        _row_get(row, "city"),
        display_query_ward(_row_get(row, "ward")),
        _row_get(row, "asset_type"),
        _row_get(row, "year"),
        _row_get(row, "month"),
    ]
    if all(value not in (None, "") for value in [parts[0], parts[1], parts[3], parts[4], parts[5]]):
        business_parts = [re.sub(r"[\\/:*?\"<>|]", "", str(value)) for value in parts if value not in (None, "")]
        return "物件报告-" + "-".join(business_parts) + ".html"
    created_at = str(_row_get(row, "created_at") or "")
    date_match = re.match(r"(\d{4})[-年](\d{2})[-月](\d{2})", created_at)
    date_text = "".join(date_match.groups()) if date_match else datetime.now().strftime("%Y%m%d")
    return f"物件报告-{date_text}.html"


def render_report_download(row: Any) -> str:
    """Render only business-facing report data into one dependency-free HTML file."""

    report = row_to_report(row)
    summary = _report_json_value(row, "summary", {})
    summary_text = summary if isinstance(summary, str) else summary.get("line") or summary.get("title") or "暂无概要"
    sales = _report_json_value(row, "sale", [])
    source_rows = _report_json_value(row, "data_sources", [])
    limitations = _row_get(row, "limitations") or "报告数字仅代表所标注期间和口径，不构成单套物件估价。"
    address = _row_get(row, "address") or _row_get(row, "location") or report.get("title") or "未标注地区"
    source_items = []
    for source in source_rows if isinstance(source_rows, list) else []:
        if not isinstance(source, dict):
            source_items.append(str(source))
            continue
        source_name = source.get("name") or "已登记数据来源"
        period = source.get("period") or _row_get(row, "source_period") or "期间未标注"
        usage = source.get("usage") or "用途按报告口径使用"
        rights = source.get("rights") or "授权状态按来源登记"
        source_items.append(f"{source_name}；期间：{period}；用途：{usage}；使用说明：{rights}")
    if not source_items:
        source_items.append(f"已登记来源；期间：{_row_get(row, 'source_period') or '期间未标注'}")
    sale_rows = []
    for sale in sales if isinstance(sales, list) else []:
        if not isinstance(sale, dict):
            continue
        layout = sale.get("layout") or "户型未标注"
        amount = sale.get("amount_yen")
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            amount_text = f"{amount:,.0f} 日元"
        else:
            amount_text = "金额未标注"
        sale_rows.append(f"<tr><td>{_html_text(layout)}</td><td>{_html_text(amount_text)}</td></tr>")
    if not sale_rows:
        sale_rows.append('<tr><td colspan="2">成交数据暂缺</td></tr>')
    generated_at = _row_get(row, "created_at") or "生成时间未标注"
    return """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.6;color:#17233d;max-width:900px;margin:0 auto;padding:32px;background:#f7f8fb}}
main{{background:#fff;padding:32px;border:1px solid #dfe4ee;border-radius:12px}} h1{{margin-top:0}} h2{{border-bottom:1px solid #dfe4ee;padding-bottom:6px;margin-top:30px}}
dt{{color:#65718a;font-size:.85rem}} dd{{margin:0 0 12px;font-weight:600}} table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #dfe4ee;padding:8px;text-align:left}} th{{background:#eef2f8}}
pre{{white-space:pre-wrap;font:inherit}} @media print{{body{{background:#fff;padding:0}}main{{border:0;padding:0}}}}
</style></head>
<body><main>
<h1>{title}</h1><p>{address}</p>
<dl><dt>生成时间</dt><dd>{generated_at}</dd><dt>数据来源与期间</dt><dd>{sources}</dd></dl>
<h2>报告概要</h2><p>{summary}</p>
<h2>成交数据</h2><table><thead><tr><th>户型</th><th>成交金额</th></tr></thead><tbody>{sales}</tbody></table>
<h2>口径与限制</h2><p>{limitations}</p>
<h2>报告正文</h2><pre>{markdown}</pre>
</main></body></html>""".format(
        title=_html_text(report.get("title") or "物件报告"),
        address=_html_text(address),
        generated_at=_html_text(generated_at),
        sources=_html_list(source_items),
        summary=_html_text(summary_text),
        sales="".join(sale_rows),
        limitations=_html_text(limitations),
        markdown=_html_text(report.get("markdown") or "暂无正文"),
    )


async def save_report(query_id: str, owner_user_id: str, report: dict[str, Any]) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into property_reports
              (query_id, owner_user_id, query_key, slug, title, publish_month, markdown, xhs_content, rental, sale, summary, images, data_sources, raw_record,
               report_status, data_class, source_id, source_period, observed_at, transformation_version, report_version, limitations)
            values
              ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14::jsonb,
               $15,
               case when $16::uuid is null then null
                    else (select data_class from public.sources where id=$16::uuid)
               end,
               $16, $17, $18, $19, $20, $21)
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
              report_status = excluded.report_status,
              data_class = excluded.data_class,
              source_id = excluded.source_id,
              source_period = excluded.source_period,
              observed_at = excluded.observed_at,
              transformation_version = excluded.transformation_version,
              report_version = excluded.report_version,
              limitations = excluded.limitations,
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
            report["report_status"],
            report.get("source_id"),
            report.get("source_period"),
            report.get("observed_at"),
            report.get("transformation_version"),
            report.get("report_version"),
            report.get("limitations"),
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
            report = build_sale_report(snapshot, request.model_dump(), owner_user_id=owner_user_id)
            async with get_pool().acquire() as conn:
                source_id = await resolve_market_source_id(conn)
            report.update(
                report_status=report_status_for_report(has_snapshot=True),
                source_id=source_id,
                source_period=snapshot.sale_period or f"{request.year}-{request.month:02d}",
                observed_at=datetime.now(timezone.utc),
                transformation_version="market-engine-v1",
                report_version="market-engine-v1",
                limitations="中古マンション成交均价的授权聚合口径；不包含挂牌价、租金或单套估价。",
            )
        else:
            title = query_title(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month)
            report = {
                "slug": namespaced_report_slug(
                    owner_user_id,
                    query_key(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month).replace("::", "_"),
                ),
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
                "report_status": report_status_for_report(has_snapshot=False),
                "data_class": None,
                "source_period": f"{request.year}-{request.month:02d}",
                "observed_at": datetime.now(timezone.utc),
                "transformation_version": "market-engine-v1",
                "limitations": "该地区或资产类型暂无已接入的授权覆盖，未编造市场数字。",
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
        error_payload = job_error_payload(exc)
        logger.exception("report generation failed", extra={"error_code": error_payload["code"]})
        async with get_pool().acquire() as conn:
            await conn.execute("update queries set status='failed', updated_at=now() where id=$1", query_id)
            await conn.execute(
                "update generation_jobs set status='failed', progress=100, current_step='失败', error_message=$2, updated_at=now() where id=$1",
                job_id,
                json.dumps(error_payload, ensure_ascii=False),
            )
            await conn.execute(
                """
                update property_reports
                set report_status='insufficient_data',
                    title=case when title='' then '报告生成失败' else title end,
                    markdown=case when markdown='' then '报告生成失败，暂无可验证数据。' else markdown end,
                    summary=case when summary='{}'::jsonb then '{"title":"数据不足","line":"报告生成失败，暂无可验证数据。"}'::jsonb else summary end,
                    updated_at=now()
                where query_id=$1 and report_status='generating'
                """,
                query_id,
            )
        raise


async def create_or_get_query_job(
    request: QueryRequest,
    user_id: str,
) -> dict[str, Any]:
    """Create or reuse the single report pipeline entry for one owner's query."""

    base_key = query_key(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month)
    key = f"{user_id}::{base_key}"
    title = query_title(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            # Serialize retries for the same key because generation_jobs has
            # historically allowed more than one row per query_id.
            await conn.execute("select pg_advisory_xact_lock(hashtext($1))", key)
            existing = await conn.fetchrow(
                """
                select pr.*, q.id as existing_query_id,
                       gj.id as existing_job_id, gj.status as existing_job_status
                from queries q
                join property_reports pr on pr.query_id=q.id
                left join lateral (
                    select id, status
                    from generation_jobs
                    where query_id=q.id
                    order by created_at desc
                    limit 1
                ) gj on true
                where q.query_key=$1
                """,
                key,
            )
            if existing:
                report_status = _row_get(existing, "report_status", "generating")
                job_status = _row_get(existing, "existing_job_status")
                action = cached_report_action(job_status, report_status)
                if action == "cache":
                    return {"query_key": key, "status": "completed", "cached": True, "title": title, "job_id": None, "report": row_to_report(existing)}
                if action == "wait":
                    return {
                        "query_key": key,
                        "status": "pending",
                        "cached": False,
                        "title": title,
                        "job_id": str(existing["existing_job_id"]),
                        "report": None,
                    }
                if action == "requeue":
                    await conn.execute(
                        """
                        update generation_jobs
                        set status='pending', progress=5, current_step='任务已重新排队',
                            error_message=null, updated_at=now()
                        where id=$1 and status in ('failed', 'completed', 'succeeded')
                        """,
                        existing["existing_job_id"],
                    )
                    await conn.execute(
                        "update queries set status='pending', updated_at=now() where id=$1",
                        existing["existing_query_id"],
                    )
                    job_id = existing["existing_job_id"]
                    query_id = existing["existing_query_id"]
                    await enqueue_report_outbox(
                        conn,
                        generation_job_id=job_id,
                        query_id=query_id,
                        owner_user_id=user_id,
                        request=request,
                    )
                else:
                    return {
                        "query_key": key,
                        "status": "pending",
                        "cached": False,
                        "title": title,
                        "job_id": str(existing["existing_job_id"]) if existing["existing_job_id"] else None,
                        "report": None,
                    }
            else:
                existing_query = await conn.fetchrow("select id from queries where query_key=$1", key)
                if existing_query is None:
                    await consume_current_entitlement(
                        conn,
                        user=AuthUser(UUID(str(user_id)), "", ""),
                        metric="query",
                        units=1,
                        idempotency_key=f"query:{key}",
                        fingerprint=f"query:{key}",
                    )

                query_id = await conn.fetchval(
                    """
                    insert into queries(query_key, owner_user_id, prefecture, city, ward, asset_type, year, month, status)
                    values($1, $2, $3, $4, $5, $6, $7, $8, 'pending')
                    on conflict(query_key) do update set updated_at=now()
                    returning id
                    """,
                    key, user_id, request.prefecture, request.city, request.ward or "", request.asset_type, request.year, request.month,
                )
                job = await conn.fetchrow(
                    "select id, status from generation_jobs where query_id=$1 order by created_at desc limit 1",
                    query_id,
                )
                if job and job["status"] == "running":
                    job_id = job["id"]
                elif job and job["status"] == "pending":
                    job_id = job["id"]
                elif job:
                    await conn.execute(
                        "update generation_jobs set status='pending', progress=5, current_step='任务已重新排队', error_message=null, updated_at=now() where id=$1",
                        job["id"],
                    )
                    job_id = job["id"]
                else:
                    job_id = await conn.fetchval(
                        "insert into generation_jobs(query_id, status, progress, current_step) values($1, 'pending', 5, '任务已创建') returning id",
                        query_id,
                    )
                await enqueue_report_outbox(
                    conn,
                    generation_job_id=job_id,
                    query_id=query_id,
                    owner_user_id=user_id,
                    request=request,
                )
    return {"query_key": key, "status": "pending", "cached": False, "title": title, "job_id": str(job_id), "report": None}


@app.post("/api/query", response_model=QueryResponse)
async def query_report(
    request: QueryRequest,
    user: AuthUser = Depends(require_user),
) -> QueryResponse:
    try:
        result = await create_or_get_query_job(request, str(user.user_id))
    except QuotaExceeded:
        return JSONResponse(status_code=429, content={"error": {"code": "quota_exceeded", "message": "query quota exceeded"}})
    return QueryResponse(query_key=result["query_key"], status=result["status"], cached=result["cached"], title=result["title"], job_id=result["job_id"], report=result["report"], message="命中历史数据" if result["cached"] else "已创建生成任务")


@app.post("/api/jobs/{query_id}/run", response_model=JobResponse, status_code=202)
async def run_legacy_job(
    query_id: str,
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
        await enqueue_report_outbox(
            conn,
            generation_job_id=job_id,
            query_id=row["query_id"],
            owner_user_id=user.user_id,
            request=request,
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
            select gj.*, q.query_key
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
            query_key=str(job["query_key"]) if job["query_key"] else None,
            status=job["status"],
            progress=job["progress"],
            current_step=job["current_step"],
            error_message=(parse_job_error(job["error_message"]) or {}).get("message"),
            error=parse_job_error(job["error_message"]),
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
        for job in item.get("generation_jobs") or []:
            error = parse_job_error(job.get("error_message"))
            job["error"] = error
            job["error_message"] = error["message"] if error else None
        result.append(item)
    return result


@app.get("/api/reports/{query_key}")
async def get_my_report(query_key: str, user: Optional[AuthUser] = Depends(optional_user)) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            select pr.*, q.prefecture, q.city, q.ward, q.asset_type, q.year, q.month
            from property_reports pr
            join queries q on q.id = pr.query_id
            where pr.query_key=$1
            limit 1
            """,
            query_key,
        )
        if not row:
            raise HTTPException(status_code=404, detail="report not found")
        owner_user_id = _row_get(row, "owner_user_id")
        unlocked = bool(
            user
            and owner_user_id is not None
            and str(owner_user_id) == str(user.user_id)
            and await _has_report_unlock(conn, user.user_id, query_key)
        )
    if not unlocked:
        return public_report_from_row(row, query_key)
    return row_to_report(row)


@app.get("/api/reports/{query_key}/download")
async def download_my_report(query_key: str, user: AuthUser = Depends(require_user)) -> Response:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            select pr.*
            from property_reports pr
            join queries q on q.id = pr.query_id
            where pr.query_key=$1 and pr.owner_user_id=$2
            limit 1
            """,
            query_key,
            user.user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail={"code": "report_not_found", "message": "报告不存在。"})
        if not await _has_report_unlock(conn, user.user_id, query_key):
            raise HTTPException(status_code=403, detail={"code": "report_locked", "message": "报告尚未解锁。"})
    filename = _download_filename(row)
    content_disposition = (
        f"attachment; filename=report.html; filename*=UTF-8''{quote(filename, safe='')}"
    )
    return Response(
        content=render_report_download(row),
        media_type="text/html",
        headers={
            "Content-Disposition": content_disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )

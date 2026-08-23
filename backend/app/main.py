import os
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .db import close, connect, get_pool, init_schema
from .jphouse_service import (
    fallback_sources,
    match_local_record,
    placeholder_xhs,
    query_key,
    query_title,
    report_from_local_record,
)
from .models import JobResponse, QueryRequest, QueryResponse


ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:8790,http://localhost:8790,https://gordon310.github.io",
    ).split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    if os.getenv("INIT_SCHEMA", "true").lower() == "true":
        await init_schema()
    yield
    await close()


app = FastAPI(title="ZOU SEEKING HOUSE JPHOUSE API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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


async def save_report(query_id: str, report: dict[str, Any]) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into property_reports
              (query_id, slug, title, publish_month, markdown, xhs_content, rental, sale, summary, images, data_sources, raw_record)
            values
              ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb)
            on conflict (query_id) do update set
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


async def run_generation_job(job_id: str, query_id: str, request: QueryRequest) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update generation_jobs set status='running', progress=20, current_step='检查本地历史数据', updated_at=now() where id=$1",
            job_id,
        )
    try:
        record = match_local_record(
            request.prefecture,
            request.city,
            request.ward,
            request.asset_type,
            request.year,
            request.month,
        )
        if record:
            report = report_from_local_record(record)
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
            await conn.execute(
                "update generation_jobs set progress=75, current_step='保存数据和索引', updated_at=now() where id=$1",
                job_id,
            )
        await save_report(query_id, report)
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
async def query_report(request: QueryRequest, background_tasks: BackgroundTasks) -> QueryResponse:
    key = query_key(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month)
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
            insert into queries(query_key, prefecture, city, ward, asset_type, year, month, status)
            values($1, $2, $3, $4, $5, $6, $7, 'pending')
            on conflict(query_key) do update set updated_at=now()
            returning id
            """,
            key,
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
    background_tasks.add_task(run_generation_job, str(job_id), str(query_id), request)
    return QueryResponse(query_key=key, status="pending", cached=False, title=title, job_id=str(job_id), message="已创建生成任务")


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    async with get_pool().acquire() as conn:
        job = await conn.fetchrow("select * from generation_jobs where id=$1", job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        report = None
        if job["status"] == "completed":
            row = await conn.fetchrow(
                """
                select pr.*
                from generation_jobs gj
                join property_reports pr on pr.query_id = gj.query_id
                where gj.id=$1
                """,
                job_id,
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

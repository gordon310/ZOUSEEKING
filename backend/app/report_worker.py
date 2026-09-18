"""Durable PostgreSQL worker contract for long-running member reports."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg

from .db import get_pool
from .models import QueryRequest


logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
LEASE_SECONDS = 900
BACKOFF_SECONDS = (5, 30, 300)


@dataclass(frozen=True)
class ClaimedReport:
    outbox_id: UUID
    generation_job_id: UUID
    query_id: UUID
    claim_token: UUID
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


@dataclass(frozen=True)
class Failure:
    code: str
    retryable: bool
    public_message: str


def claim_sql() -> str:
    return """
    with candidate as (
      select id
      from public.report_generation_outbox
      where attempts < max_attempts
        and (
          (status in ('pending', 'retryable') and next_attempt_at <= now())
          or (status = 'running' and claimed_at < now() - make_interval(secs => $1))
        )
      order by created_at asc, id asc
      for update skip locked
      limit 1
    )
    update public.report_generation_outbox outbox
       set status = 'running',
           attempts = outbox.attempts + 1,
           claim_token = gen_random_uuid(),
           claimed_at = now(),
           updated_at = now()
     from candidate
     where outbox.id = candidate.id
    returning outbox.id, outbox.generation_job_id, outbox.query_id,
              outbox.claim_token, outbox.payload, outbox.attempts, outbox.max_attempts
    """


async def enqueue_report_outbox(
    conn: asyncpg.Connection,
    *,
    generation_job_id: UUID | str,
    query_id: UUID | str,
    owner_user_id: UUID | str,
    request: QueryRequest,
) -> None:
    payload = request.model_dump()
    payload["owner_user_id"] = str(owner_user_id)
    key = f"report:{query_id}"
    await conn.execute(
        """
        insert into public.report_generation_outbox
          (generation_job_id, query_id, idempotency_key, payload)
        values ($1, $2, $3, $4::jsonb)
        on conflict (generation_job_id) do update set
          status = case when report_generation_outbox.status = 'completed' then 'completed' else 'pending' end,
          payload = excluded.payload,
          next_attempt_at = now(),
          claim_token = null,
          claimed_at = null,
          last_error_code = null,
          last_error_message = null,
          updated_at = now()
        """,
        generation_job_id,
        query_id,
        key,
        json.dumps(payload, ensure_ascii=False),
    )


async def claim_next(pool: asyncpg.Pool) -> ClaimedReport | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(claim_sql(), LEASE_SECONDS)
    if row is None:
        return None
    raw_payload = row["payload"] or {}
    payload = json.loads(raw_payload) if isinstance(raw_payload, str) else dict(raw_payload)
    return ClaimedReport(
        outbox_id=row["id"],
        generation_job_id=row["generation_job_id"],
        query_id=row["query_id"],
        claim_token=row["claim_token"],
        payload=payload,
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
    )


async def complete_claim(pool: asyncpg.Pool, claim: ClaimedReport) -> bool:
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            """
            update public.report_generation_outbox
               set status='completed', completed_at=now(), updated_at=now(),
                   last_error_code=null, last_error_message=null
             where id=$1 and status='running' and claim_token=$2
            returning id
            """,
            claim.outbox_id,
            claim.claim_token,
        )
    return updated is not None


def backoff_seconds(attempt: int) -> int:
    return BACKOFF_SECONDS[min(max(attempt - 1, 0), len(BACKOFF_SECONDS) - 1)]


def classify_failure(error: BaseException) -> Failure:
    if isinstance(error, (TimeoutError, asyncio.TimeoutError, OSError, asyncpg.PostgresConnectionError)):
        return Failure("dependency_timeout", True, "报告生成依赖暂时不可用，请稍后重试。")
    if getattr(error, "code", None) == "market_source_unavailable":
        return Failure("market_source_unavailable", True, "市场数据源暂时不可用，请稍后重试。")
    return Failure("report_generation_failed", False, "报告生成失败，请稍后重试。")


async def record_failure(pool: asyncpg.Pool, claim: ClaimedReport, failure: Failure) -> str:
    retry = failure.retryable and claim.attempts < claim.max_attempts
    status = "retryable" if retry else "failed"
    delay = backoff_seconds(claim.attempts)
    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                """
                update public.report_generation_outbox
                   set status=$3,
                       next_attempt_at=case when $3='retryable' then now() + make_interval(secs => $4) else now() end,
                       last_error_code=$5, last_error_message=$6,
                       updated_at=now()
                 where id=$1 and status='running' and claim_token=$2
                returning id
                """,
                claim.outbox_id,
                claim.claim_token,
                status,
                delay,
                failure.code,
                failure.public_message,
            )
            if updated is not None:
                await conn.execute(
                    """
                    update public.generation_jobs
                       set status=$2,
                           progress=case when $2='pending' then 5 else 100 end,
                           current_step=case when $2='pending' then '任务已重新排队' else '失败' end,
                           error_message=case when $2='failed' then $3 else null end,
                           updated_at=now()
                     where id=$1
                    """,
                    claim.generation_job_id,
                    "pending" if retry else "failed",
                    json.dumps({"code": failure.code, "message": failure.public_message}, ensure_ascii=False),
                )
                await conn.execute(
                    """
                    update public.queries
                       set status=$2, updated_at=now()
                     where id=$1
                    """,
                    claim.query_id,
                    "pending" if retry else "failed",
                )
    return status


async def process_once(pool: asyncpg.Pool | None = None) -> dict[str, Any] | None:
    pool = pool or get_pool()
    claim = await claim_next(pool)
    if claim is None:
        return None
    request = QueryRequest(**{key: value for key, value in claim.payload.items() if key != "owner_user_id"})
    try:
        # The API never calls this function.  Importing lazily keeps the report
        # engine in one implementation while avoiding an app/worker cycle.
        from .main import run_generation_job

        await run_generation_job(
            str(claim.generation_job_id),
            str(claim.query_id),
            str(claim.payload["owner_user_id"]),
            request,
        )
    except Exception as exc:
        failure = classify_failure(exc)
        status = await record_failure(pool, claim, failure)
        logger.exception("report worker execution failed", extra={"error_code": failure.code})
        return {"job_id": str(claim.generation_job_id), "status": status, "code": failure.code}
    await complete_claim(pool, claim)
    return {"job_id": str(claim.generation_job_id), "status": "completed"}


async def run_worker(*, once: bool = False, poll_seconds: float = 1.0) -> None:
    pool = get_pool()
    while True:
        result = await process_once(pool)
        if once or result is not None:
            if once:
                return
        if result is None:
            await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker(once=os.environ.get("REPORT_WORKER_ONCE") == "1"))

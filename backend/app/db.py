from __future__ import annotations

import os
from pathlib import Path

import asyncpg


DATABASE_URL = os.getenv("DATABASE_URL", "")
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "backend" / "sql" / "schema.sql"

pool: asyncpg.Pool | None = None


async def connect() -> None:
    global pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)


async def close() -> None:
    global pool
    if pool:
        await pool.close()
        pool = None


def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("Database pool is not initialized")
    return pool


async def init_schema() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    async with get_pool().acquire() as conn:
        await conn.execute(sql)

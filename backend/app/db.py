from __future__ import annotations

import os

import asyncpg


DATABASE_URL = os.getenv("DATABASE_URL", "")

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

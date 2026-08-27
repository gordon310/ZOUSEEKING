from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from ..db import get_pool


router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", include_in_schema=False)
async def legacy_health() -> dict[str, str]:
    """Backward-compatible liveness endpoint for existing local clients."""
    return await live()


@router.get("/health/ready")
async def ready() -> dict[str, str]:
    try:
        async with get_pool().acquire() as conn:
            await conn.fetchval("select 1")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {
        "status": "ready",
        "database": "ok",
        "version": os.getenv("APP_VERSION", "0.1.0"),
    }

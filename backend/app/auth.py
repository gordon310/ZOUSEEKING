"""Minimal Supabase Auth token verification for the FastAPI boundary."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Optional
from uuid import UUID
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class AuthUser:
    user_id: UUID
    email: str
    username: str


def _fetch_supabase_user(access_token: str) -> dict:
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    if not base_url or not anon_key:
        raise RuntimeError("Supabase Auth verification is not configured")
    request = Request(
        f"{base_url}/auth/v1/user",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Supabase access token") from exc


async def require_user(authorization: Optional[str] = Header(default=None)) -> AuthUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录。")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录。")
    try:
        payload = await asyncio.to_thread(_fetch_supabase_user, token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="认证服务尚未配置") from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录。") from exc
    user_id_text = str(payload.get("id") or "").strip()
    if not user_id_text:
        raise HTTPException(status_code=401, detail="认证用户信息不完整。")
    try:
        user_id = UUID(user_id_text)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="认证用户信息不完整。") from exc
    metadata = payload.get("user_metadata") or {}
    return AuthUser(
        user_id=user_id,
        email=str(payload.get("email") or ""),
        username=str(metadata.get("username") or metadata.get("name") or payload.get("email") or "用户"),
    )

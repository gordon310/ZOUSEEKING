"""Public endpoint for consumer account creation with an optional invite source."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from ..db import get_pool
from ..invites import InviteCodeError, InviteRegistration, register_invited_user
from ..rate_limit import RateLimitStoreUnavailable, abuse_subject_hash, configured_limit, consume_shared_rate_limit

router=APIRouter(prefix="/api/auth",tags=["auth"])
class InviteRegisterRequest(BaseModel):
 email:str=Field(min_length=3,max_length=320); password:str=Field(min_length=6,max_length=128)
 username:str=Field(min_length=1,max_length=120); invite_code:str=Field(default="",max_length=128)
 consent_version:str=Field(default="",max_length=80); terms_version:str=Field(default="",max_length=80)
@router.post("/invite-register",status_code=201)
async def invite_register(body:InviteRegisterRequest,request:Request)->dict[str,Any]:
 forwarded=request.headers.get("x-forwarded-for","").split(",",1)[0].strip()
 host=forwarded or (request.client.host if request.client else "")
 try:
  ip_hash=abuse_subject_hash("consumer_registration",host or "unknown")
  limit=configured_limit("INVITE_REGISTER_RATE_LIMIT_PER_HOUR",5)
  async with get_pool().acquire() as conn:
   if await consume_shared_rate_limit(conn,ip_hash,"consumer_registration",limit,datetime.now(timezone.utc)) is None:
    raise HTTPException(status_code=429,detail={"code":"rate_limited"},headers={"Retry-After":"3600"})
   return await register_invited_user(conn,InviteRegistration(email=body.email,password=body.password,username=body.username,invite_code=body.invite_code,consent_version=body.consent_version,terms_version=body.terms_version,ip_hash=ip_hash))
 except RateLimitStoreUnavailable as exc:
  # Fail closed: allowing registration during a lost shared counter defeats the abuse boundary.
  raise HTTPException(status_code=503,detail={"code":"rate_limit_unavailable"}) from exc
 except InviteCodeError as exc: raise HTTPException(status_code=exc.status_code,detail={"code":exc.code}) from exc

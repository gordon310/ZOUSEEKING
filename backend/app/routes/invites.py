"""Public endpoint for invite-only consumer account creation."""
from __future__ import annotations
import hashlib
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from ..db import get_pool
from ..invites import InviteCodeError, InviteRegistration, register_invited_user

router=APIRouter(prefix="/api/auth",tags=["auth"])
class InviteRegisterRequest(BaseModel):
 email:str=Field(min_length=3,max_length=320); password:str=Field(min_length=6,max_length=128)
 username:str=Field(min_length=1,max_length=120); invite_code:str=Field(min_length=1,max_length=128)
 consent_version:str=Field(default="",max_length=80); terms_version:str=Field(default="",max_length=80)
@router.post("/invite-register",status_code=201)
async def invite_register(body:InviteRegisterRequest,request:Request)->dict[str,Any]:
 forwarded=request.headers.get("x-forwarded-for","").split(",",1)[0].strip()
 host=forwarded or (request.client.host if request.client else "")
 ip_hash=hashlib.sha256(host.encode()).hexdigest() if host else None
 try:
  async with get_pool().acquire() as conn:
   return await register_invited_user(conn,InviteRegistration(email=body.email,password=body.password,username=body.username,invite_code=body.invite_code,consent_version=body.consent_version,terms_version=body.terms_version,ip_hash=ip_hash))
 except InviteCodeError as exc: raise HTTPException(status_code=exc.status_code,detail={"code":exc.code}) from exc

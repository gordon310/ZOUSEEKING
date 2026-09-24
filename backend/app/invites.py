"""Server-only invite reservation and Supabase Admin user creation."""
from __future__ import annotations
import asyncio, hashlib, json, os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID
import asyncpg
from . import timeouts

# § 邀请码为可选来源。
INVITE_REQUIRED_OPERATIONS=frozenset({"consumer_registration"})
class InviteCodeError(Exception):
 def __init__(self,code:str,status_code:int=400)->None: super().__init__(code); self.code=code; self.status_code=status_code
def normalize_invite_code(value:str)->str:
 code=(value or "").strip().lower()
 if not code or len(code)>128: raise InviteCodeError("invite_code_invalid",400)
 return code
def _email_hash(email:str)->str: return hashlib.sha256(email.strip().lower().encode()).hexdigest()
def _admin_create_user(payload:dict[str,Any])->dict[str,Any]:
 base=os.getenv("SUPABASE_URL","").rstrip("/"); key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","")
 if not base or not key: raise InviteCodeError("invite_service_unavailable",503)
 request=Request(f"{base}/auth/v1/admin/users",method="POST",headers={"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json"},data=json.dumps(payload).encode())
 try:
  with urlopen(request,timeout=timeouts.DEFAULT_OUTBOUND_TIMEOUT_SECONDS) as response: return json.loads(response.read().decode())
 except HTTPError as exc:
  if exc.code in (400,409,422): raise InviteCodeError("account_already_exists",409) from exc
  raise InviteCodeError("invite_service_unavailable",503) from exc
 except (URLError,TimeoutError,json.JSONDecodeError) as exc: raise InviteCodeError("invite_service_unavailable",503) from exc
@dataclass(frozen=True)
class InviteRegistration:
 email:str; password:str; username:str; invite_code:str; consent_version:str=""; terms_version:str=""; ip_hash:str|None=None
async def _create_consumer_user(registration:InviteRegistration,email:str,consent_source:str)->UUID:
 created=await asyncio.to_thread(_admin_create_user,{"email":email,"password":registration.password,"email_confirm":False,"user_metadata":{"username":registration.username,"audience":"c","consent_version":registration.consent_version,"terms_version":registration.terms_version,"consent_source":consent_source}})
 return UUID(str(created["id"]))
async def register_invited_user(conn:asyncpg.Connection,registration:InviteRegistration)->dict[str,str]:
 if registration.invite_code=="":
  email=registration.email.strip().lower()
  if not email or "@" not in email: raise InviteCodeError("invite_registration_invalid",400)
  user_id=await _create_consumer_user(registration,email,"consumer_registration")
  return {"user_id":str(user_id),"email":email}
 code=normalize_invite_code(registration.invite_code); email=registration.email.strip().lower()
 if not email or "@" not in email: raise InviteCodeError("invite_registration_invalid",400)
 row=await conn.fetchrow("select redemption_id,state from public.reserve_invite_code($1,$2,$3)",code,_email_hash(email),registration.ip_hash)
 if not row or row["state"]!="reserved" or row["redemption_id"] is None:
  state=str(row["state"]) if row else "unavailable"
  raise InviteCodeError(f"invite_code_{state}", 409 if state=="exhausted" else 403)
 redemption_id=row["redemption_id"]
 try:
  user_id=await _create_consumer_user(registration,email,"invite_registration")
  if not await conn.fetchval("select public.complete_invite_redemption($1,$2)",redemption_id,user_id): raise InviteCodeError("invite_service_unavailable",503)
  return {"user_id":str(user_id),"email":email}
 except Exception:
  await conn.execute("select public.release_invite_reservation($1)",redemption_id); raise

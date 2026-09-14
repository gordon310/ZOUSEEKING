#!/usr/bin/env python3
"""Run authenticated live quota evidence without persisting credentials.

Required environment variables are intentionally read at runtime only:
QUOTA_ACCEPTANCE_BASE_URL, QUOTA_ACCEPTANCE_SUPABASE_URL,
QUOTA_ACCEPTANCE_SERVICE_ROLE_KEY,
QUOTA_ACCEPTANCE_USER_A_TOKEN, QUOTA_ACCEPTANCE_USER_B_TOKEN,
QUOTA_ACCEPTANCE_PLAN_CODE, QUOTA_ACCEPTANCE_ENTITLEMENT_ID.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
SERVER_USER_AGENT = "JPPropDIs-staging-quota-acceptance/1.0"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    token: str = "",
    body: Optional[object] = None,
    user_agent: str = BROWSER_USER_AGENT,
) -> dict:
    if not user_agent.strip():
        raise ValueError("User-Agent is required")
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": user_agent,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["apikey"] = token
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url.rstrip('/')}{path}", method=method, headers=headers, data=None if body is None else json.dumps(body).encode())
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw
            return {"status": response.status, "body": parsed}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return {"status": exc.code, "body": parsed}
    except URLError as exc:
        return {"status": None, "body": f"transport error: {exc.reason}"}


def _entitlement(base_url: str, key: str, entitlement_id: str) -> dict:
    return _request(
        base_url,
        f"/rest/v1/plan_entitlements?id=eq.{entitlement_id}&select=id,plan_code,metric,period,limit_units,active,effective_from",
        token=key,
        user_agent=SERVER_USER_AGENT,
    )


def _set_limit(base_url: str, key: str, entitlement_id: str, value: int) -> dict:
    return _request(
        base_url,
        f"/rest/v1/plan_entitlements?id=eq.{entitlement_id}",
        method="PATCH",
        token=key,
        body={"limit_units": value},
        user_agent=SERVER_USER_AGENT,
    )


def _restore_limit(base_url: str, key: str, entitlement_id: str, original: object) -> dict:
    """Always restore the acceptance baseline, even after an earlier failure."""
    target = 3
    if not isinstance(original, dict):
        return _set_limit(base_url, key, entitlement_id, target)
    rows = original.get("body")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        limit_units = rows[0].get("limit_units")
        if not isinstance(limit_units, bool) and isinstance(limit_units, (int, float)):
            target = int(limit_units)
    try:
        return _set_limit(base_url, key, entitlement_id, target)
    except Exception as exc:  # keep the finally path alive so AFTER is still observed
        return {"status": None, "body": f"restore failed: {type(exc).__name__}"}


def _require_uncached(response: dict) -> dict:
    body = response.get("body") if isinstance(response, dict) else None
    if isinstance(body, dict) and body.get("cached") is True:
        raise AssertionError("response was cached; it cannot prove quota consumption")
    return response


def _delete_auth_user(base_url: str, key: str, user_id: str) -> dict:
    return _request(
        base_url,
        f"/auth/v1/admin/users/{user_id}",
        method="DELETE",
        token=key,
        user_agent=SERVER_USER_AGENT,
    )


def _me(base_url: str, token: str) -> dict:
    return _request(base_url, "/api/me", token=token)


def _delete_owned_rows(base_url: str, key: str, user_id: str) -> list[dict]:
    """Delete only rows owned by the two synthetic acceptance users."""
    results = []
    filters = {
        "queries": f"owner_user_id=eq.{user_id}",
        "property_reports": f"owner_user_id=eq.{user_id}",
        "data_sources": f"owner_user_id=eq.{user_id}",
        "properties": f"owner_user_id=eq.{user_id}",
        "analysis_sessions": f"owner_user_id=eq.{user_id}",
        "exports": f"owner_user_id=eq.{user_id}",
        "usage_quotas": f"scope_key=eq.user:{user_id}",
        "usage_idempotency": f"scope_key=eq.user:{user_id}",
        "usage_events": f"scope_key=eq.user:{user_id}",
    }
    for table, filter_query in filters.items():
        results.append({
            "table": table,
            "response": _request(
                base_url,
                f"/rest/v1/{table}?{filter_query}",
                method="DELETE",
                token=key,
                user_agent=SERVER_USER_AGENT,
            ),
        })
    return results


def _read_owned_rows(base_url: str, key: str, user_id: str) -> list[dict]:
    results = []
    for table, filter_query in {
        "queries": f"owner_user_id=eq.{user_id}",
        "property_reports": f"owner_user_id=eq.{user_id}",
        "data_sources": f"owner_user_id=eq.{user_id}",
        "properties": f"owner_user_id=eq.{user_id}",
        "analysis_sessions": f"owner_user_id=eq.{user_id}",
        "exports": f"owner_user_id=eq.{user_id}",
        "usage_quotas": f"scope_key=eq.user:{user_id}",
        "usage_idempotency": f"scope_key=eq.user:{user_id}",
        "usage_events": f"scope_key=eq.user:{user_id}",
    }.items():
        results.append({"table": table, "response": _request(base_url, f"/rest/v1/{table}?{filter_query}&select=*", token=key, user_agent=SERVER_USER_AGENT)})
    return results


def _query(base_url: str, token: str, month: int, username: str = "", asset_type: str = "塔楼") -> dict:
    return _request(
        base_url,
        "/api/query",
        method="POST",
        token=token,
        body={"prefecture": "大阪府", "city": "大阪市", "ward": "北区", "asset_type": asset_type, "year": 2099, "month": month, "username": username},
    )


async def _parallel_queries(base_url: str, token: str, asset_prefix: str) -> list[dict]:
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [loop.run_in_executor(executor, _query, base_url, token, month, "", f"{asset_prefix}-{month}") for month in range(1, 9)]
        return await asyncio.gather(*futures)


def main() -> int:
    api_base_url = _required("QUOTA_ACCEPTANCE_BASE_URL")
    supabase_base_url = _required("QUOTA_ACCEPTANCE_SUPABASE_URL")
    service_key = _required("QUOTA_ACCEPTANCE_SERVICE_ROLE_KEY")
    user_a = _required("QUOTA_ACCEPTANCE_USER_A_TOKEN")
    user_b = _required("QUOTA_ACCEPTANCE_USER_B_TOKEN")
    entitlement_id = _required("QUOTA_ACCEPTANCE_ENTITLEMENT_ID")

    original = None
    exit_code = 0
    run_id = uuid.uuid4().hex[:12]
    asset_prefix = f"塔楼-qa-{run_id}"
    try:
        original = _entitlement(supabase_base_url, service_key, entitlement_id)
        print("ENTITLEMENT_BEFORE=" + json.dumps(original, ensure_ascii=False, sort_keys=True))
        print("SET_LIMIT_1=" + json.dumps(_set_limit(supabase_base_url, service_key, entitlement_id, 1), ensure_ascii=False, sort_keys=True))
        first = _query(api_base_url, user_a, 1, "attacker", f"{asset_prefix}-1")
        print("FIRST_UNCACHED_CALL=" + json.dumps(_require_uncached(first), ensure_ascii=False, sort_keys=True))
        second = _query(api_base_url, user_a, 2, "attacker", f"{asset_prefix}-2")
        print("SECOND_UNCACHED_CALL(429)=" + json.dumps(second, ensure_ascii=False, sort_keys=True))
        print("SET_LIMIT_2=" + json.dumps(_set_limit(supabase_base_url, service_key, entitlement_id, 2), ensure_ascii=False, sort_keys=True))
        same_first = _require_uncached(_query(api_base_url, user_a, 3, asset_type=f"{asset_prefix}-3"))
        same_second = _query(api_base_url, user_a, 3, asset_type=f"{asset_prefix}-3")
        print("同序列两次调用=" + json.dumps({"first": same_first, "second": same_second}, ensure_ascii=False, sort_keys=True))
        concurrency = asyncio.run(_parallel_queries(api_base_url, user_a, asset_prefix))
        print("CONCURRENCY=" + json.dumps({"responses": concurrency, "success_count": sum(200 <= (r.get("status") or 0) < 300 for r in concurrency), "429_count": sum(r.get("status") == 429 for r in concurrency), "over_limit": sum(200 <= (r.get("status") or 0) < 300 for r in concurrency) > 2}, ensure_ascii=False, sort_keys=True))
        print("A_B_ISOLATION=" + json.dumps({"user_a": _me(api_base_url, user_a), "user_b": _require_uncached(_query(api_base_url, user_b, 1, asset_type=f"{asset_prefix}-b1"))}, ensure_ascii=False, sort_keys=True))
        forged = _require_uncached(_query(api_base_url, user_b, 2, "user-a-forged", f"{asset_prefix}-b2"))
        print("FORGED_BODY_IDENTITY=" + json.dumps(forged, ensure_ascii=False, sort_keys=True))
        anonymous = _request(api_base_url, "/api/query", method="POST", body={"prefecture": "大阪府", "city": "大阪市", "ward": "北区", "asset_type": f"{asset_prefix}-anon", "year": 2099, "month": 12})
        print("ANONYMOUS=" + json.dumps(anonymous, ensure_ascii=False, sort_keys=True))
    except Exception as exc:
        exit_code = 1
        print("ACCEPTANCE_ERROR=" + json.dumps({"error": type(exc).__name__}, ensure_ascii=False, sort_keys=True))
    finally:
        print("RESTORE=" + json.dumps(_restore_limit(supabase_base_url, service_key, entitlement_id, original), ensure_ascii=False, sort_keys=True))
        try:
            after = _entitlement(supabase_base_url, service_key, entitlement_id)
        except Exception as exc:
            after = {"status": None, "body": f"entitlement-after failed: {type(exc).__name__}"}
        print("ENTITLEMENT_AFTER=" + json.dumps(after, ensure_ascii=False, sort_keys=True))
        cleanup = []
        for token in (user_a, user_b):
            try:
                me = _me(api_base_url, token)
                user_id = (me.get("body") or {}).get("user_id") if isinstance(me, dict) else None
                if user_id:
                    cleanup.append({"user_id": user_id, "rows": _delete_owned_rows(supabase_base_url, service_key, user_id), "auth": _delete_auth_user(supabase_base_url, service_key, user_id)})
                else:
                    cleanup.append({"user_id": None, "me": me, "deleted": False})
            except Exception as exc:
                cleanup.append({"deleted": False, "error": type(exc).__name__})
        print("TEST_USERS_CLEANUP=" + json.dumps(cleanup, ensure_ascii=False, sort_keys=True))
        zero_read = []
        for item in cleanup:
            if item.get("user_id"):
                zero_read.append({"user_id": item["user_id"], "rows": _read_owned_rows(supabase_base_url, service_key, item["user_id"]), "auth_refresh": _me(api_base_url, user_a if item["user_id"] == cleanup[0].get("user_id") else user_b)})
        print("POST_DELETE_ZERO_READ=" + json.dumps(zero_read, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

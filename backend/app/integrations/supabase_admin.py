"""Small, fail-closed Supabase Auth Admin client."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

logger = logging.getLogger(__name__)


class SupabaseAdminError(RuntimeError):
    def __init__(self, category: str, *, retryable: bool = True) -> None:
        super().__init__(category)
        self.category = category
        self.retryable = retryable


class SupabaseAdmin:
    def __init__(self, *, base_url: str | None = None, service_role_key: str | None = None, timeout_seconds: float = 8.0) -> None:
        self.base_url = (base_url if base_url is not None else os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.service_role_key = service_role_key if service_role_key is not None else os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.base_url and self.service_role_key)

    async def revoke_all_sessions(self, user_id: UUID, access_token: str | None) -> None:
        if not access_token:
            raise SupabaseAdminError("missing_request_access_token", retryable=False)
        await self._request("/auth/v1/logout?scope=global", method="POST", bearer=access_token)

    async def anonymize_user(self, user_id: UUID) -> None:
        await self._request(
            f"/auth/v1/admin/users/{user_id}",
            method="PUT",
            payload={
                "email": f"deleted+{user_id}@invalid",
                "phone": "",
                "user_metadata": {"username": "", "name": "", "display_name": "", "deleted_account": True},
                "ban_duration": "876000h",
            },
        )

    async def _request(self, path: str, *, method: str, bearer: str | None = None, payload: Mapping[str, object] | None = None) -> None:
        if not self.is_configured():
            raise SupabaseAdminError("supabase_admin_not_configured", retryable=False)
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {bearer or self.service_role_key}",
            "Accept": "application/json",
        }
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            await asyncio.to_thread(self._urlopen, request)
        except HTTPError as exc:
            retryable = exc.code >= 500 or exc.code in {408, 429}
            logger.warning("supabase admin request failed category=http_%s", exc.code)
            raise SupabaseAdminError(f"http_{exc.code}", retryable=retryable) from None
        except (URLError, TimeoutError, OSError):
            logger.warning("supabase admin request failed category=transport")
            raise SupabaseAdminError("transport", retryable=True) from None

    def _urlopen(self, request: Request) -> bytes:
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read()

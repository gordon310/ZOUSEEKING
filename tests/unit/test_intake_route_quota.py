from uuid import UUID

import pytest
from fastapi import BackgroundTasks

from backend.app.auth import AuthUser
from backend.app.intake.models import ConvertSessionRequest
from backend.app.intake.repository import ConvertedProject
from backend.app.routes.intake import convert_session
from backend.app.usage.ledger import QuotaExceeded


class ConvertedRepository:
    async def convert_to_user(self, session_id, token_hash, user_id, project_name):
        return ConvertedProject(user_id, UUID("00000000-0000-0000-0000-000000000099"))


@pytest.mark.asyncio
async def test_convert_returns_structured_client_error_when_quota_is_unconfigured():
    async def unavailable_pipeline(*args, **kwargs):
        raise QuotaExceeded("usage quota is not configured")

    with pytest.raises(Exception) as raised:
        await convert_session(
            UUID("00000000-0000-0000-0000-000000000001"),
            BackgroundTasks(),
            ConvertSessionRequest(prefecture="大阪府", city="大阪市", ward="北区", asset_type="公寓"),
            "session-token",
            AuthUser(UUID("00000000-0000-0000-0000-000000000002"), "member@example.com", "Member"),
            ConvertedRepository(),
            unavailable_pipeline,
        )

    assert raised.value.status_code == 429
    assert raised.value.detail == {
        "code": "quota_unavailable",
        "message": "当前会员额度尚未配置，暂时无法完成项目转换，请稍后再试。",
    }


@pytest.mark.asyncio
async def test_preview_quota_error_uses_preview_specific_safe_message():
    from backend.app.routes.intake import _quota_http_exception

    error = _quota_http_exception(QuotaExceeded("usage quota is not configured"), action="preview")

    assert error.status_code == 429
    assert error.detail["message"] == "当前会员额度尚未配置，暂时无法生成免费预览，请稍后再试。"


@pytest.mark.asyncio
async def test_convert_returns_structured_client_error_when_quota_is_exhausted():
    async def exhausted_pipeline(*args, **kwargs):
        raise QuotaExceeded("usage quota exceeded")

    with pytest.raises(Exception) as raised:
        await convert_session(
            UUID("00000000-0000-0000-0000-000000000001"),
            BackgroundTasks(),
            ConvertSessionRequest(prefecture="大阪府", city="大阪市", ward="北区", asset_type="公寓"),
            "session-token",
            AuthUser(UUID("00000000-0000-0000-0000-000000000002"), "member@example.com", "Member"),
            ConvertedRepository(),
            exhausted_pipeline,
        )

    assert raised.value.status_code == 429
    assert raised.value.detail == {
        "code": "quota_exceeded",
        "message": "本周期可用额度已用尽，暂时无法完成项目转换。",
    }

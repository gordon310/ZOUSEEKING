from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.service_tasks import (
    ServiceTaskApply,
    ServiceTaskCreate,
    allowed_transition,
    require_transition,
    serialize_task,
)


def test_frozen_transition_matrix_requires_consent_before_progress():
    assert allowed_transition("open", "matched_pending_consent")
    assert not allowed_transition("open", "in_progress")
    assert not allowed_transition("completion_pending", "completed")


def test_completed_transition_is_only_creator_confirmation():
    with pytest.raises(HTTPException) as exc:
        require_transition("completion_pending", "completed", actor="org")
    assert exc.value.status_code == 409
    require_transition("completion_pending", "completed", actor="creator")


def test_application_requires_assigned_member_user_id():
    with pytest.raises(ValueError):
        ServiceTaskApply()
    body = ServiceTaskApply(assigned_member_user_id="00000000-0000-0000-0000-000000000001")
    assert str(body.assigned_member_user_id).endswith("0001")


def test_task_serialization_has_no_contact_or_assignee_fields():
    row = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000002",
        purpose="现场看房",
        region_pref="大阪",
        asset_type="apartment",
        compensation="paid",
        public_description="需要机构协助并提交客观记录。",
        apply_deadline=datetime(2026, 9, 30, tzinfo=timezone.utc),
        status="open",
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        application_status="pending",
        creator_consent_status="granted",
    )
    result = serialize_task(row)
    assert result["status"] == "open"
    assert result["application_status"] == "pending"
    assert result["creator_consent_status"] == "granted"
    assert "assignee_organization_id" not in result
    assert not any("email" in key or "phone" in key for key in result)


def test_create_only_accepts_draft_or_open():
    with pytest.raises(ValueError):
        ServiceTaskCreate(
            purpose="x",
            compensation="paid",
            public_description="short description",
            status="completed",
        )

from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.intake.models import (
    ConfirmFieldRequest,
    CreateInputRequest,
    CreateSessionRequest,
)


def test_session_accepts_only_two_purposes():
    request = CreateSessionRequest(purpose="self_use", consent_version="privacy-2026-08")
    assert request.purpose == "self_use"

    with pytest.raises(ValidationError):
        CreateSessionRequest(purpose="flip", consent_version="privacy-2026-08")


def test_url_input_requires_https_and_safe_host():
    with pytest.raises(ValidationError):
        CreateInputRequest(input_type="url", source_url="http://example.com/listing")
    with pytest.raises(ValidationError):
        CreateInputRequest(input_type="url", source_url="https://user:password@example.com/listing")
    with pytest.raises(ValidationError):
        CreateInputRequest(input_type="url", source_url="https://localhost/listing")


def test_text_input_has_a_length_limit():
    with pytest.raises(ValidationError):
        CreateInputRequest(input_type="text", raw_text="x" * 20001)

    request = CreateInputRequest(input_type="text", raw_text="大阪市北区，售价3500万日元")
    assert request.raw_text.startswith("大阪市")


def test_manual_field_unit_is_server_derived_and_identity_fields_are_rejected():
    field = ConfirmFieldRequest(
        field_name="asking_price_jpy",
        value=35000000,
        confirmation_status="confirmed",
        source_input_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    assert field.unit == "JPY"

    with pytest.raises(ValidationError):
        ConfirmFieldRequest(field_name="owner_user_id", value="attacker", confirmation_status="confirmed")
    with pytest.raises(ValidationError):
        ConfirmFieldRequest(
            field_name="asking_price_jpy",
            value=35000000,
            unit="USD",
            confirmation_status="confirmed",
        )


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        ConfirmFieldRequest(field_name="not_a_project_field", value="x", confirmation_status="confirmed")

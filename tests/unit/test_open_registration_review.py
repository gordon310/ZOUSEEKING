"""Guards for the offline open-registration review checker (countdown D-6).

The checker only has value if it actually fails when the declared posture
drifts, so every criterion is exercised twice: once against this checkout and
once against a copy where the criterion was deliberately violated (mutation).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "check_open_registration_review.py"

STAGED_FILES = (
    "backend/app/routes/invites.py",
    "backend/app/invites.py",
    "backend/app/integrations/supabase_admin.py",
    "docs/operations/production-configuration-contract.md",
    "deploy/.env.example",
    "web/profile.html",
    "web/index.html",
    "web-source/app.js",
    "docs/release/launch-announcement-2026-10-07.md",
)


def load_checker():
    spec = importlib.util.spec_from_file_location("open_registration_review", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stage_repo(tmp_path: Path) -> Path:
    for relative in STAGED_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return tmp_path


def mutate(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert old in text, f"mutation anchor is missing from {relative}: {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def failed_ids(result: dict) -> set[str]:
    return {check["id"] for check in result["checks"] if not check["ok"]}


def test_checker_passes_on_this_checkout() -> None:
    checker = load_checker()
    result, errors = checker.audit(ROOT)

    assert errors == []
    assert result["status"] == "pass"
    assert result["production_contacted"] is False
    assert result["network_used"] is False
    assert failed_ids(result) == set()
    assert {check["id"] for check in result["checks"]} == {
        "C1_registration_request_optional_invite_code",
        "C2_open_registration_skips_invite_tables",
        "C3_admin_create_pre_confirms_email",
        "C4_registration_rate_limit_fails_closed",
        "C5_consumer_signup_never_requires_invite_code",
        "C6_four_language_open_registration_alignment",
    }
    # The enumeration signal is reported but never gates the run.
    assert result["findings"] and any("account_already_exists" in finding for finding in result["findings"])
    assert result["not_executed"]


def test_checker_cli_is_reproducible_and_reports_no_network() -> None:
    completed = subprocess.run(
        ["python3", "scripts/check_open_registration_review.py", "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "pass"
    assert payload["checks"]

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for forbidden in ("import socket", "import urllib", "import requests", "import httpx", "subprocess.run"):
        assert forbidden not in source, f"the review checker must stay offline, found {forbidden}"


def test_checker_rejects_a_required_invite_code(tmp_path: Path) -> None:
    checker = load_checker()
    staged = stage_repo(tmp_path)
    mutate(
        staged,
        "backend/app/routes/invites.py",
        'Field(default="",max_length=128)',
        "Field(min_length=1,max_length=128)",
    )

    result, errors = checker.audit(staged)

    assert errors
    assert "C1_registration_request_optional_invite_code" in failed_ids(result)


def test_checker_rejects_a_broken_open_registration_shortcut(tmp_path: Path) -> None:
    checker = load_checker()
    staged = stage_repo(tmp_path)
    mutate(staged, "backend/app/invites.py", 'if registration.invite_code=="":', "if False:")

    result, errors = checker.audit(staged)

    assert errors
    assert "C2_open_registration_skips_invite_tables" in failed_ids(result)


def test_checker_rejects_an_unconfirmed_admin_creation(tmp_path: Path) -> None:
    checker = load_checker()
    staged = stage_repo(tmp_path)
    mutate(staged, "backend/app/invites.py", '"email_confirm":True', '"email_confirm":False')

    result, errors = checker.audit(staged)

    assert errors
    assert "C3_admin_create_pre_confirms_email" in failed_ids(result)


def test_checker_rejects_an_unregistered_rate_limit_key(tmp_path: Path) -> None:
    checker = load_checker()
    staged = stage_repo(tmp_path)
    mutate(staged, "deploy/.env.example", "INVITE_REGISTER_RATE_LIMIT_PER_HOUR=5", "")

    result, errors = checker.audit(staged)

    assert errors
    assert "C4_registration_rate_limit_fails_closed" in failed_ids(result)


def test_checker_rejects_a_required_invite_field_on_the_shared_page(tmp_path: Path) -> None:
    checker = load_checker()
    staged = stage_repo(tmp_path)
    mutate(
        staged,
        "web/index.html",
        '<input id="registerInviteCode" type="text" autocomplete="off"',
        '<input id="registerInviteCode" type="text" required autocomplete="off"',
    )

    result, errors = checker.audit(staged)

    assert errors
    assert "C5_consumer_signup_never_requires_invite_code" in failed_ids(result)


def test_checker_rejects_drifted_announcement_languages(tmp_path: Path) -> None:
    checker = load_checker()
    staged = stage_repo(tmp_path)
    mutate(staged, "docs/release/launch-announcement-2026-10-07.md", "无需邀请码", "需邀请码")

    result, errors = checker.audit(staged)

    assert errors
    assert "C6_four_language_open_registration_alignment" in failed_ids(result)


def test_checker_rejects_an_unfilled_announcement_placeholder(tmp_path: Path) -> None:
    checker = load_checker()
    staged = stage_repo(tmp_path)
    announcement = staged / "docs/release/launch-announcement-2026-10-07.md"
    announcement.write_text(
        announcement.read_text(encoding="utf-8") + "\n- 支持 SLA: TBD\n",
        encoding="utf-8",
    )

    result, errors = checker.audit(staged)

    assert errors
    assert "C6_four_language_open_registration_alignment" in failed_ids(result)


@pytest.mark.asyncio
async def test_no_invite_registration_payload_pre_confirms_email_and_records_consumer_consent(monkeypatch) -> None:
    from backend.app import invites

    payloads: list[dict] = []

    def create_user(payload):
        payloads.append(payload)
        return {"id": "00000000-0000-0000-0000-000000000009"}

    async def run_inline(function, payload):
        return function(payload)

    monkeypatch.setattr(invites, "_admin_create_user", create_user)
    monkeypatch.setattr(invites.asyncio, "to_thread", run_inline)

    class _Connection:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def fetchrow(self, *args):
            self.calls.append("reserve")
            return {"redemption_id": None, "state": "reserved"}

    connection = _Connection()
    result = await invites.register_invited_user(
        connection,
        invites.InviteRegistration("open@example.com", "password", "open-user", ""),
    )

    assert connection.calls == []
    assert payloads[0]["email_confirm"] is True
    assert payloads[0]["user_metadata"]["consent_source"] == "consumer_registration"
    assert result["email"] == "open@example.com"

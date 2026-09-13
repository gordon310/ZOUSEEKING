from __future__ import annotations

import httpx

from scripts.staging_m1_acceptance import StagingM1Acceptance


def _acceptance(handler):
    transport = httpx.MockTransport(handler)
    acceptance = StagingM1Acceptance("https://staging.example", "anon", "service")
    acceptance.client = httpx.Client(
        base_url="https://staging.example", transport=transport
    )
    return acceptance


def test_seed_profiles_reuses_trigger_created_profile_without_insert() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{"user_id": "owner", "email": ""}],
                request=request,
            )
        raise AssertionError("trigger-created profile must not be inserted")

    acceptance = _acceptance(handler)
    try:
        acceptance._seed_profiles(
            [
                {"user_id": "owner", "email": "", "bio": "synthetic"},
            ]
        )
    finally:
        acceptance.close()

    assert calls == [("GET", "/rest/v1/user_profiles")]
    assert acceptance.fixture_ids["user_profiles"] == ["owner"]


def test_cleanup_continues_after_item_failure_and_runs_zero_self_check(capsys) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/storage/v1/object/property-intake"):
            raise httpx.ConnectError("synthetic failure", request=request)
        if request.url.path.startswith("/auth/v1/admin/users"):
            return httpx.Response(200, json={"users": []}, request=request)
        if request.url.path.startswith("/rest/v1/"):
            return httpx.Response(200, json=[], request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    acceptance = _acceptance(handler)
    acceptance.storage_paths.add("m1-synthetic/run/fixture.png")
    acceptance.fixture_ids["queries"] = ["query-id"]
    acceptance.created_user_ids.add("user-id")
    acceptance._created_user_ids = {"user-id"}
    acceptance._created_user_emails = {"user@example.invalid"}
    try:
        acceptance.cleanup()
    finally:
        acceptance.close()

    output = capsys.readouterr().out
    assert "cleanup storage" in output
    assert "cleanup table queries" in output
    assert "cleanup auth user user-id" in output
    assert "self-check example.invalid users=0" in output
    assert "self-check related rows=0" in output
    assert acceptance.cleanup_errors == ["storage_object"]

"""Run M1 acceptance checks against the single documented staging project.

The command creates only synthetic .invalid Auth users and synthetic fixture
rows/objects, then always attempts cleanup. Secrets and generated identities
are never emitted.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence
from urllib.parse import quote

import httpx


STAGING_PROJECT_REF = "fnogxuytbabxmqousifh"
STAGING_URL = f"https://{STAGING_PROJECT_REF}.supabase.co"
STORAGE_BUCKET = "property-intake"
SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "token_hash",
    "hashed_token",
    "email_otp",
    "action_link",
    "password",
    "old_password",
    "new_password",
    "api_key",
    "key",
    "secret",
    "service_role",
    "anon",
}


class AcceptanceError(RuntimeError):
    """A sanitized M1 acceptance failure."""


def validate_live_target(project_ref: str, base_url: str, allow_live: bool) -> str:
    if not allow_live:
        raise ValueError("explicit live staging flag is required")
    if project_ref != STAGING_PROJECT_REF:
        raise ValueError("only the exact staging project is allowed")
    normalized = base_url.rstrip("/")
    if normalized != STAGING_URL:
        raise ValueError("only the exact staging URL is allowed")
    return normalized


def _key_items(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("apiKeys", "api_keys", "keys", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    raise ValueError("unexpected Supabase API key response")


def select_legacy_keys(payload: Any) -> tuple[str, str]:
    values: dict[str, str] = {}
    for item in _key_items(payload):
        name = str(item.get("name") or item.get("type") or "").lower()
        value = item.get("api_key") or item.get("key") or item.get("value")
        if name in {"anon", "service_role"} and isinstance(value, str) and value:
            values[name] = value
    if set(values) != {"anon", "service_role"}:
        raise ValueError("legacy anon/service_role keys are required")
    return values["anon"], values["service_role"]


def redact_evidence(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (
                "<redacted>"
                if str(key).lower() in SENSITIVE_KEYS
                else redact_evidence(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_evidence(item) for item in value]
    if isinstance(value, tuple):
        return [redact_evidence(item) for item in value]
    return value


def _load_legacy_keys(project_ref: str) -> tuple[str, str]:
    result = subprocess.run(
        [
            "supabase",
            "projects",
            "api-keys",
            "--project-ref",
            project_ref,
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AcceptanceError(
            "unable to obtain staging API keys from authenticated CLI"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AcceptanceError(
            "Supabase CLI returned invalid API-key metadata"
        ) from exc
    try:
        return select_legacy_keys(payload)
    except ValueError as exc:
        raise AcceptanceError(str(exc)) from exc


def _response_json(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def _safe_error_code(response: httpx.Response) -> str:
    payload = _response_json(response)
    if isinstance(payload, Mapping):
        for key in ("error_code", "code", "error"):
            value = payload.get(key)
            if isinstance(value, str) and len(value) <= 80:
                return value
    return "http_error"


def _expect(
    response: httpx.Response,
    statuses: Iterable[int],
    label: str,
) -> httpx.Response:
    if response.status_code not in set(statuses):
        raise AcceptanceError(
            f"{label} returned HTTP {response.status_code} "
            f"({_safe_error_code(response)})"
        )
    return response


def _user_payload(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        nested = payload.get("user")
        if isinstance(nested, Mapping):
            return nested
        return payload
    return {}


class StagingM1Acceptance:
    def __init__(
        self,
        base_url: str,
        anon_key: str,
        service_key: str,
        timeout_seconds: float = 25.0,
    ) -> None:
        self.base_url = base_url
        self.anon_key = anon_key
        self.service_key = service_key
        self.client = httpx.Client(base_url=base_url, timeout=timeout_seconds)
        self.run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + secrets.token_hex(4)
        )
        self.created_user_ids: set[str] = set()
        self.fixture_ids: MutableMapping[str, list[str]] = {}
        self.storage_paths: set[str] = set()
        self.cleanup_errors: list[str] = []
        self.evidence: dict[str, Any] = {
            "target": {
                "project_ref": STAGING_PROJECT_REF,
                "host": f"{STAGING_PROJECT_REF}.supabase.co",
                "environment": "staging",
            },
            "fixture_class": "synthetic_fixture",
            "run_id_hash": hashlib.sha256(self.run_id.encode()).hexdigest()[:16],
            "gate_status": "running",
            "checks": {},
        }

    def close(self) -> None:
        self.client.close()

    def _headers(
        self,
        identity: str,
        access_token: Optional[str] = None,
        content_type: Optional[str] = "application/json",
    ) -> dict[str, str]:
        if identity == "service":
            key = self.service_key
            bearer = self.service_key
        elif identity == "anon":
            key = self.anon_key
            bearer = self.anon_key
        elif identity == "user":
            if not access_token:
                raise AcceptanceError("user identity requires an access token")
            key = self.anon_key
            bearer = access_token
        else:
            raise AcceptanceError("unknown HTTP identity")
        headers = {"apikey": key, "Authorization": f"Bearer {bearer}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        identity: str,
        access_token: Optional[str] = None,
        json_body: Any = None,
        content: Optional[bytes] = None,
        params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> httpx.Response:
        request_headers = self._headers(
            identity,
            access_token,
            None if content is not None else "application/json",
        )
        if headers:
            request_headers.update(headers)
        return self.client.request(
            method,
            path,
            headers=request_headers,
            json=json_body,
            content=content,
            params=params,
        )

    def _admin_create_user(
        self, email: str, password: str, *, confirmed: bool
    ) -> Mapping[str, Any]:
        response = _expect(
            self._request(
                "POST",
                "/auth/v1/admin/users",
                identity="service",
                json_body={
                    "email": email,
                    "password": password,
                    "email_confirm": confirmed,
                    "user_metadata": {
                        "data_class": "synthetic_fixture",
                        "m1_run": self.run_id,
                    },
                },
            ),
            {200, 201},
            "admin create synthetic user",
        )
        user = _user_payload(_response_json(response))
        user_id = user.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise AcceptanceError("admin create user response omitted user id")
        self.created_user_ids.add(user_id)
        return user

    def _sign_in(self, email: str, password: str) -> Mapping[str, Any]:
        response = _expect(
            self._request(
                "POST",
                "/auth/v1/token",
                identity="anon",
                params={"grant_type": "password"},
                json_body={"email": email, "password": password},
            ),
            {200},
            "password sign-in",
        )
        payload = _response_json(response)
        if not isinstance(payload, Mapping):
            raise AcceptanceError("password sign-in returned invalid JSON")
        if not payload.get("access_token") or not payload.get("refresh_token"):
            raise AcceptanceError("password sign-in omitted session tokens")
        return payload

    def _rest(
        self,
        method: str,
        table: str,
        *,
        identity: str,
        access_token: Optional[str] = None,
        body: Any = None,
        params: Optional[Mapping[str, str]] = None,
        prefer: Optional[str] = None,
    ) -> httpx.Response:
        headers = {"Prefer": prefer} if prefer else None
        return self._request(
            method,
            f"/rest/v1/{table}",
            identity=identity,
            access_token=access_token,
            json_body=body,
            params=params,
            headers=headers,
        )

    def _record_fixture(self, table: str, *row_ids: str) -> None:
        self.fixture_ids.setdefault(table, []).extend(row_ids)

    def check_auth_settings_and_confirmation(
        self, owner_email: str, owner_password: str
    ) -> None:
        settings_response = _expect(
            self._request("GET", "/auth/v1/settings", identity="anon"),
            {200},
            "Auth settings",
        )
        settings = _response_json(settings_response)
        if not isinstance(settings, Mapping):
            raise AcceptanceError("Auth settings returned invalid JSON")
        confirm_required = settings.get("mailer_autoconfirm") is False
        if not confirm_required:
            raise AcceptanceError(
                "hosted staging email confirmation is not required"
            )

        missing_email = f"m1-missing-{self.run_id}@example.invalid"
        signup_email = f"m1-signup-{self.run_id}@example.invalid"
        signup_password = "M1!" + secrets.token_urlsafe(18) + "aA9"
        generated_signup = _expect(
            self._request(
                "POST",
                "/auth/v1/admin/generate_link",
                identity="service",
                json_body={
                    "type": "signup",
                    "email": signup_email,
                    "password": signup_password,
                    "data": {"data_class": "synthetic_fixture"},
                },
            ),
            {200},
            "synthetic signup-link generation",
        )
        signup_payload = _response_json(generated_signup)
        signup_user = _user_payload(signup_payload)
        signup_id = signup_user.get("id")
        if not isinstance(signup_id, str) or not signup_id:
            raise AcceptanceError("signup-link response omitted user id")
        self.created_user_ids.add(signup_id)
        if signup_user.get("email_confirmed_at") or signup_user.get("confirmed_at"):
            raise AcceptanceError(
                "signup-link creation unexpectedly confirmed email"
            )

        unconfirmed_sign_in = self._request(
            "POST",
            "/auth/v1/token",
            identity="anon",
            params={"grant_type": "password"},
            json_body={"email": signup_email, "password": signup_password},
        )
        _expect(
            unconfirmed_sign_in,
            {400},
            "unconfirmed email sign-in rejection",
        )

        signup_properties = (
            signup_payload.get("properties", {})
            if isinstance(signup_payload, Mapping)
            else {}
        )
        if not isinstance(signup_properties, Mapping):
            signup_properties = {}
        signup_token_hash = signup_properties.get("hashed_token") or (
            signup_payload.get("hashed_token")
            if isinstance(signup_payload, Mapping)
            else None
        )
        verification_type = (
            signup_properties.get("verification_type")
            or signup_properties.get("email_action_type")
            or "signup"
        )
        if not isinstance(signup_token_hash, str) or not signup_token_hash:
            raise AcceptanceError("signup-link response omitted token hash")
        confirmed = _expect(
            self._request(
                "POST",
                "/auth/v1/verify",
                identity="anon",
                json_body={
                    "type": verification_type,
                    "token_hash": signup_token_hash,
                },
            ),
            {200},
            "synthetic email confirmation token verification",
        )
        confirmed_payload = _response_json(confirmed)
        if not isinstance(confirmed_payload, Mapping) or not confirmed_payload.get(
            "access_token"
        ):
            raise AcceptanceError("email confirmation omitted a session")
        self._sign_in(signup_email, signup_password)

        duplicate = _expect(
            self._request(
                "POST",
                "/auth/v1/signup",
                identity="anon",
                json_body={"email": signup_email, "password": signup_password},
            ),
            {200},
            "duplicate signup enumeration check",
        )
        duplicate_payload = _response_json(duplicate)
        duplicate_user = _user_payload(duplicate_payload)
        if duplicate_user.get("id") == signup_id:
            raise AcceptanceError(
                "duplicate signup exposed the existing user id"
            )
        if isinstance(duplicate_payload, Mapping) and (
            duplicate_payload.get("access_token")
            or duplicate_payload.get("session")
        ):
            raise AcceptanceError(
                "duplicate signup unexpectedly received a session"
            )

        wrong_existing = self._request(
            "POST",
            "/auth/v1/token",
            identity="anon",
            params={"grant_type": "password"},
            json_body={
                "email": owner_email,
                "password": owner_password + "-wrong",
            },
        )
        wrong_missing = self._request(
            "POST",
            "/auth/v1/token",
            identity="anon",
            params={"grant_type": "password"},
            json_body={
                "email": missing_email,
                "password": owner_password + "-wrong",
            },
        )
        if (
            wrong_existing.status_code != wrong_missing.status_code
            or _safe_error_code(wrong_existing) != _safe_error_code(wrong_missing)
        ):
            raise AcceptanceError(
                "password sign-in error reveals account existence"
            )

        self.evidence["checks"]["auth_confirmation_enumeration"] = {
            "status": "pass",
            "confirm_email_required": True,
            "unconfirmed_sign_in": "denied",
            "confirmation_token": "verified",
            "confirmed_sign_in": "accepted",
            "duplicate_existing_id_exposed": False,
            "invalid_login_response_uniform": True,
            "public_recovery_email_delivery": "not_executed_no_smtp_sink",
        }

    def check_password_recovery(
        self, owner_email: str, old_password: str
    ) -> tuple[str, Mapping[str, Any]]:
        generated = _expect(
            self._request(
                "POST",
                "/auth/v1/admin/generate_link",
                identity="service",
                json_body={"type": "recovery", "email": owner_email},
            ),
            {200},
            "admin recovery-link generation",
        )
        generated_payload = _response_json(generated)
        properties = (
            generated_payload.get("properties", {})
            if isinstance(generated_payload, Mapping)
            else {}
        )
        if not isinstance(properties, Mapping):
            properties = {}
        token_hash = properties.get("hashed_token") or (
            generated_payload.get("hashed_token")
            if isinstance(generated_payload, Mapping)
            else None
        )
        if not isinstance(token_hash, str) or not token_hash:
            raise AcceptanceError(
                "recovery-link response omitted token hash"
            )

        verified = _expect(
            self._request(
                "POST",
                "/auth/v1/verify",
                identity="anon",
                json_body={"type": "recovery", "token_hash": token_hash},
            ),
            {200},
            "recovery token verification",
        )
        recovery_session = _response_json(verified)
        if not isinstance(recovery_session, Mapping) or not recovery_session.get(
            "access_token"
        ):
            raise AcceptanceError(
                "recovery verification omitted access token"
            )

        new_password = "M1!" + secrets.token_urlsafe(20) + "aA9"
        _expect(
            self._request(
                "PUT",
                "/auth/v1/user",
                identity="user",
                access_token=str(recovery_session["access_token"]),
                json_body={"password": new_password},
            ),
            {200},
            "password update from recovery session",
        )

        old_sign_in = self._request(
            "POST",
            "/auth/v1/token",
            identity="anon",
            params={"grant_type": "password"},
            json_body={"email": owner_email, "password": old_password},
        )
        _expect(old_sign_in, {400}, "old password rejection")
        new_session = self._sign_in(owner_email, new_password)
        self.evidence["checks"]["auth_password_recovery"] = {
            "status": "pass",
            "recovery_link_generated": True,
            "recovery_token_verified": True,
            "password_updated": True,
            "old_password_rejected": True,
            "new_password_accepted": True,
        }
        return new_password, new_session

    @staticmethod
    def _uuid() -> str:
        value = secrets.token_hex(16)
        return (
            value[0:8]
            + "-"
            + value[8:12]
            + "-"
            + value[12:16]
            + "-"
            + value[16:20]
            + "-"
            + value[20:32]
        )

    def seed_rls_fixtures(
        self, owner_id: str, other_id: str
    ) -> dict[str, str]:
        ids = {
            name: self._uuid()
            for name in (
                "active_option",
                "inactive_option",
                "owner_query",
                "other_query",
                "owner_job",
                "other_job",
                "owner_report",
                "other_report",
                "owner_property",
                "other_property",
                "worker_query",
            )
        }

        option_type = f"m1_fixture_{self.run_id}"
        options = [
            {
                "id": ids["active_option"],
                "option_type": option_type,
                "value": "active",
                "label": "M1 synthetic active",
                "is_active": True,
            },
            {
                "id": ids["inactive_option"],
                "option_type": option_type,
                "value": "inactive",
                "label": "M1 synthetic inactive",
                "is_active": False,
            },
        ]
        _expect(
            self._rest(
                "POST",
                "query_field_options",
                identity="service",
                body=options,
                prefer="return=minimal",
            ),
            {201},
            "worker seed field options",
        )
        self._record_fixture(
            "query_field_options",
            ids["active_option"],
            ids["inactive_option"],
        )

        queries = [
            {
                "id": ids["owner_query"],
                "query_key": f"m1-owner-{self.run_id}",
                "prefecture": "synthetic",
                "city": "synthetic",
                "asset_type": "synthetic_fixture",
                "year": 2026,
                "month": 9,
                "owner_user_id": owner_id,
            },
            {
                "id": ids["other_query"],
                "query_key": f"m1-other-{self.run_id}",
                "prefecture": "synthetic",
                "city": "synthetic",
                "asset_type": "synthetic_fixture",
                "year": 2026,
                "month": 9,
                "owner_user_id": other_id,
            },
        ]
        _expect(
            self._rest(
                "POST",
                "queries",
                identity="service",
                body=queries,
                prefer="return=minimal",
            ),
            {201},
            "worker seed queries",
        )
        self._record_fixture(
            "queries", ids["owner_query"], ids["other_query"]
        )

        jobs = [
            {
                "id": ids["owner_job"],
                "query_id": ids["owner_query"],
                "status": "pending",
                "progress": 0,
            },
            {
                "id": ids["other_job"],
                "query_id": ids["other_query"],
                "status": "pending",
                "progress": 0,
            },
        ]
        _expect(
            self._rest(
                "POST",
                "generation_jobs",
                identity="service",
                body=jobs,
                prefer="return=minimal",
            ),
            {201},
            "worker seed jobs",
        )
        self._record_fixture(
            "generation_jobs", ids["owner_job"], ids["other_job"]
        )

        reports = [
            {
                "id": ids["owner_report"],
                "query_id": ids["owner_query"],
                "query_key": f"m1-owner-report-{self.run_id}",
                "slug": f"m1-owner-report-{self.run_id}",
                "title": "M1 synthetic owner report",
                "publish_month": "2026-09",
                "owner_user_id": owner_id,
            },
            {
                "id": ids["other_report"],
                "query_id": ids["other_query"],
                "query_key": f"m1-other-report-{self.run_id}",
                "slug": f"m1-other-report-{self.run_id}",
                "title": "M1 synthetic other report",
                "publish_month": "2026-09",
                "owner_user_id": other_id,
            },
        ]
        _expect(
            self._rest(
                "POST",
                "property_reports",
                identity="service",
                body=reports,
                prefer="return=minimal",
            ),
            {201},
            "worker seed reports",
        )
        self._record_fixture(
            "property_reports", ids["owner_report"], ids["other_report"]
        )

        properties = [
            {
                "id": ids["owner_property"],
                "owner_user_id": owner_id,
                "project_type": "residential",
                "building_name": "M1 synthetic owner property",
                "data_class": "synthetic_fixture",
            },
            {
                "id": ids["other_property"],
                "owner_user_id": other_id,
                "project_type": "residential",
                "building_name": "M1 synthetic other property",
                "data_class": "synthetic_fixture",
            },
        ]
        _expect(
            self._rest(
                "POST",
                "properties",
                identity="service",
                body=properties,
                prefer="return=minimal",
            ),
            {201},
            "worker seed properties",
        )
        self._record_fixture(
            "properties", ids["owner_property"], ids["other_property"]
        )

        profiles = [
            {
                "user_id": owner_id,
                "email": "",
                "bio": "M1 synthetic owner",
                "membership_tier": "free",
                "daily_query_limit": 3,
            },
            {
                "user_id": other_id,
                "email": "",
                "bio": "M1 synthetic other",
                "membership_tier": "free",
                "daily_query_limit": 3,
            },
        ]
        _expect(
            self._rest(
                "POST",
                "user_profiles",
                identity="service",
                body=profiles,
                prefer="return=minimal",
            ),
            {201},
            "worker seed profiles",
        )
        self._record_fixture("user_profiles", owner_id, other_id)
        return ids

    @staticmethod
    def _rows(
        response: httpx.Response, label: str
    ) -> list[Mapping[str, Any]]:
        _expect(response, {200}, label)
        payload = _response_json(response)
        if not isinstance(payload, list):
            raise AcceptanceError(f"{label} did not return a row list")
        return [row for row in payload if isinstance(row, Mapping)]

    def check_four_identity_rls(
        self,
        ids: Mapping[str, str],
        owner_id: str,
        owner_token: str,
        other_token: str,
    ) -> None:
        option_type = f"m1_fixture_{self.run_id}"
        anon_options = self._rows(
            self._rest(
                "GET",
                "query_field_options",
                identity="anon",
                params={
                    "option_type": f"eq.{option_type}",
                    "select": "id,is_active",
                },
            ),
            "anonymous active field-option read",
        )
        if [row.get("id") for row in anon_options] != [
            ids["active_option"]
        ]:
            raise AcceptanceError(
                "anonymous field-option policy did not filter inactive row"
            )
        _expect(
            self._rest(
                "GET",
                "queries",
                identity="anon",
                params={
                    "id": f"eq.{ids['owner_query']}",
                    "select": "id",
                },
            ),
            {401, 403},
            "anonymous private query denial",
        )

        owner_queries = self._rows(
            self._rest(
                "GET",
                "queries",
                identity="user",
                access_token=owner_token,
                params={
                    "id": (
                        f"in.({ids['owner_query']},{ids['other_query']})"
                    ),
                    "select": "id",
                },
            ),
            "owner query visibility",
        )
        if [row.get("id") for row in owner_queries] != [
            ids["owner_query"]
        ]:
            raise AcceptanceError(
                "owner query visibility is not owner-scoped"
            )

        for table, own_key, other_key in (
            ("generation_jobs", "owner_job", "other_job"),
            ("property_reports", "owner_report", "other_report"),
            ("properties", "owner_property", "other_property"),
        ):
            rows = self._rows(
                self._rest(
                    "GET",
                    table,
                    identity="user",
                    access_token=owner_token,
                    params={
                        "id": f"in.({ids[own_key]},{ids[other_key]})",
                        "select": "id",
                    },
                ),
                f"owner {table} visibility",
            )
            if [row.get("id") for row in rows] != [ids[own_key]]:
                raise AcceptanceError(
                    f"owner {table} visibility is not owner-scoped"
                )

        own_profile = self._rows(
            self._rest(
                "GET",
                "user_profiles",
                identity="user",
                access_token=owner_token,
                params={
                    "user_id": f"eq.{owner_id}",
                    "select": "user_id,bio",
                },
            ),
            "owner profile read",
        )
        if len(own_profile) != 1:
            raise AcceptanceError("owner profile is not visible")

        preference_update = self._rows(
            self._rest(
                "PATCH",
                "user_profiles",
                identity="user",
                access_token=owner_token,
                params={"user_id": f"eq.{owner_id}"},
                body={"bio": "M1 synthetic preference update"},
                prefer="return=representation",
            ),
            "owner preference update",
        )
        if len(preference_update) != 1:
            raise AcceptanceError(
                "owner preference update did not affect one row"
            )

        membership_update = self._rest(
            "PATCH",
            "user_profiles",
            identity="user",
            access_token=owner_token,
            params={"user_id": f"eq.{owner_id}"},
            body={
                "membership_tier": "admin",
                "daily_query_limit": 999,
            },
            prefer="return=representation",
        )
        _expect(
            membership_update,
            {400},
            "owner membership escalation denial",
        )

        direct_property = self._rest(
            "POST",
            "properties",
            identity="user",
            access_token=owner_token,
            body={
                "owner_user_id": owner_id,
                "project_type": "residential",
                "data_class": "synthetic_fixture",
            },
            prefer="return=representation",
        )
        _expect(
            direct_property,
            {401, 403},
            "owner direct property write denial",
        )

        other_visibility = self._rows(
            self._rest(
                "GET",
                "queries",
                identity="user",
                access_token=other_token,
                params={
                    "id": f"eq.{ids['owner_query']}",
                    "select": "id",
                },
            ),
            "other-user query isolation",
        )
        if other_visibility:
            raise AcceptanceError(
                "other user can read the owner's query"
            )

        other_update = self._rows(
            self._rest(
                "PATCH",
                "user_profiles",
                identity="user",
                access_token=other_token,
                params={"user_id": f"eq.{owner_id}"},
                body={"bio": "other-user mutation"},
                prefer="return=representation",
            ),
            "other-user profile isolation",
        )
        if other_update:
            raise AcceptanceError(
                "other user updated the owner's profile"
            )

        worker_query = {
            "id": ids["worker_query"],
            "query_key": f"m1-worker-{self.run_id}",
            "prefecture": "synthetic",
            "city": "synthetic",
            "asset_type": "synthetic_fixture",
            "year": 2026,
            "month": 9,
            "owner_user_id": owner_id,
        }
        _expect(
            self._rest(
                "POST",
                "queries",
                identity="service",
                body=worker_query,
                prefer="return=minimal",
            ),
            {201},
            "worker trusted write",
        )
        self._record_fixture("queries", ids["worker_query"])
        invalid_job = self._rest(
            "POST",
            "generation_jobs",
            identity="service",
            body={
                "query_id": ids["worker_query"],
                "status": "pending",
                "progress": 101,
            },
            prefer="return=minimal",
        )
        _expect(
            invalid_job,
            {400},
            "worker database constraint enforcement",
        )

        self.evidence["checks"]["database_rls_four_identity"] = {
            "status": "pass",
            "anonymous": "active-options-only",
            "owner": "own-read-and-profile-preferences-only",
            "other_authenticated": "owner-rows-hidden",
            "worker": "trusted-write-with-constraints",
        }

    def _storage_path(self) -> str:
        return f"m1-synthetic/{self.run_id}/fixture.png"

    def _storage_download(
        self,
        path: str,
        *,
        identity: str,
        access_token: Optional[str] = None,
    ) -> httpx.Response:
        encoded = quote(path, safe="/")
        return self._request(
            "GET",
            (
                f"/storage/v1/object/authenticated/"
                f"{STORAGE_BUCKET}/{encoded}"
            ),
            identity=identity,
            access_token=access_token,
        )

    def _storage_upload(
        self, path: str, content: bytes
    ) -> httpx.Response:
        encoded = quote(path, safe="/")
        return self._request(
            "POST",
            f"/storage/v1/object/{STORAGE_BUCKET}/{encoded}",
            identity="service",
            content=content,
            headers={
                "Content-Type": "image/png",
                "x-upsert": "false",
            },
        )

    def _storage_delete(self, path: str) -> httpx.Response:
        return self._request(
            "DELETE",
            f"/storage/v1/object/{STORAGE_BUCKET}",
            identity="service",
            json_body={"prefixes": [path]},
        )

    def _storage_list_contains(self, path: str) -> bool:
        directory, name = path.rsplit("/", 1)
        response = _expect(
            self._request(
                "POST",
                f"/storage/v1/object/list/{STORAGE_BUCKET}",
                identity="service",
                json_body={
                    "prefix": directory,
                    "limit": 100,
                    "offset": 0,
                    "sortBy": {"column": "name", "order": "asc"},
                },
            ),
            {200},
            "worker Storage list",
        )
        payload = _response_json(response)
        if not isinstance(payload, list):
            raise AcceptanceError("worker Storage list returned invalid JSON")
        return any(
            isinstance(item, Mapping)
            and item.get("name") in {name, path}
            for item in payload
        )

    def check_storage_four_identity(
        self, owner_token: str, other_token: str
    ) -> None:
        path = self._storage_path()
        self.storage_paths.add(path)
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
            "QVR42mP8/x8AAusB9Y9Z6ZsAAAAASUVORK5CYII="
        )
        expected_hash = hashlib.sha256(png).hexdigest()

        _expect(
            self._storage_upload(path, png),
            {200},
            "worker Storage upload",
        )
        if not self._storage_list_contains(path):
            raise AcceptanceError("uploaded Storage object is absent from listing")
        worker_download = _expect(
            self._storage_download(path, identity="service"),
            {200},
            "worker Storage download",
        )
        if (
            hashlib.sha256(worker_download.content).hexdigest()
            != expected_hash
        ):
            raise AcceptanceError(
                "worker Storage download hash mismatch"
            )

        for label, identity, token in (
            ("anonymous", "anon", None),
            ("owner", "user", owner_token),
            ("other_authenticated", "user", other_token),
        ):
            denied = self._storage_download(
                path, identity=identity, access_token=token
            )
            _expect(
                denied,
                {400, 401, 403, 404},
                f"{label} Storage denial",
            )

        _expect(
            self._storage_delete(path),
            {200},
            "worker Storage delete",
        )
        if self._storage_list_contains(path):
            raise AcceptanceError("deleted Storage object remains in listing")
        _expect(
            self._storage_upload(path, worker_download.content),
            {200},
            "worker Storage restore upload",
        )
        if not self._storage_list_contains(path):
            raise AcceptanceError("restored Storage object is absent from listing")
        restored = _expect(
            self._storage_download(path, identity="service"),
            {200},
            "worker Storage restored download",
        )
        if hashlib.sha256(restored.content).hexdigest() != expected_hash:
            raise AcceptanceError(
                "restored Storage object hash mismatch"
            )
        _expect(
            self._storage_delete(path),
            {200},
            "worker Storage final delete",
        )
        if self._storage_list_contains(path):
            raise AcceptanceError("final Storage cleanup left object metadata")
        self.storage_paths.discard(path)

        self.evidence["checks"][
            "storage_four_identity_and_restore"
        ] = {
            "status": "pass",
            "bucket": STORAGE_BUCKET,
            "bucket_visibility": "private",
            "anonymous": "denied",
            "owner": "denied-service-only-contract",
            "other_authenticated": "denied",
            "worker": "upload-download-delete-restore-delete",
            "restored_hash_match": True,
        }

    def check_logout_and_delete(
        self,
        owner_id: str,
        owner_email: str,
        password: str,
        session: Mapping[str, Any],
    ) -> None:
        refresh = _expect(
            self._request(
                "POST",
                "/auth/v1/token",
                identity="anon",
                params={"grant_type": "refresh_token"},
                json_body={"refresh_token": session["refresh_token"]},
            ),
            {200},
            "Auth refresh token rotation",
        )
        refreshed = _response_json(refresh)
        if not isinstance(refreshed, Mapping) or not refreshed.get(
            "refresh_token"
        ):
            raise AcceptanceError("Auth refresh omitted rotated token")

        _expect(
            self._request(
                "POST",
                "/auth/v1/logout",
                identity="user",
                access_token=str(refreshed["access_token"]),
                params={"scope": "global"},
            ),
            {200, 204},
            "Auth global logout",
        )
        revoked_refresh = self._request(
            "POST",
            "/auth/v1/token",
            identity="anon",
            params={"grant_type": "refresh_token"},
            json_body={"refresh_token": refreshed["refresh_token"]},
        )
        _expect(
            revoked_refresh,
            {400},
            "revoked refresh token rejection",
        )

        deletion_session = self._sign_in(owner_email, password)
        _expect(
            self._request(
                "DELETE",
                f"/auth/v1/admin/users/{owner_id}",
                identity="service",
            ),
            {200},
            "Auth hard delete synthetic user",
        )
        self.created_user_ids.discard(owner_id)
        post_delete_refresh = self._request(
            "POST",
            "/auth/v1/token",
            identity="anon",
            params={"grant_type": "refresh_token"},
            json_body={
                "refresh_token": deletion_session["refresh_token"]
            },
        )
        _expect(
            post_delete_refresh,
            {400},
            "deleted-user refresh rejection",
        )
        deleted_sign_in = self._request(
            "POST",
            "/auth/v1/token",
            identity="anon",
            params={"grant_type": "password"},
            json_body={"email": owner_email, "password": password},
        )
        _expect(
            deleted_sign_in,
            {400},
            "deleted-user sign-in rejection",
        )

        profile_rows = self._rows(
            self._rest(
                "GET",
                "user_profiles",
                identity="service",
                params={
                    "user_id": f"eq.{owner_id}",
                    "select": "user_id",
                },
            ),
            "deleted-user profile cascade",
        )
        if profile_rows:
            raise AcceptanceError(
                "deleted Auth user profile did not cascade"
            )

        self.evidence["checks"][
            "auth_logout_revocation_delete"
        ] = {
            "status": "pass",
            "refresh_rotation": True,
            "global_logout": True,
            "refresh_revoked": True,
            "hard_delete": True,
            "deleted_user_cannot_refresh_or_sign_in": True,
            "profile_cascade": True,
            "access_jwt_note": "valid_until_expiry-by-design",
        }

    def cleanup(self) -> None:
        for path in list(self.storage_paths):
            try:
                response = self._storage_delete(path)
                if (
                    response.status_code not in {200, 400, 404}
                    or self._storage_list_contains(path)
                ):
                    self.cleanup_errors.append("storage_object")
                else:
                    self.storage_paths.discard(path)
            except Exception:
                self.cleanup_errors.append("storage_object")

        delete_order = (
            "property_reports",
            "generation_jobs",
            "properties",
            "queries",
            "query_field_options",
            "user_profiles",
        )
        key_column = {"user_profiles": "user_id"}
        for table in delete_order:
            ids = self.fixture_ids.get(table, [])
            if not ids:
                continue
            column = key_column.get(table, "id")
            try:
                response = self._rest(
                    "DELETE",
                    table,
                    identity="service",
                    params={column: f"in.({','.join(ids)})"},
                    prefer="return=minimal",
                )
                if response.status_code not in {200, 204}:
                    self.cleanup_errors.append(f"table:{table}")
            except Exception:
                self.cleanup_errors.append(f"table:{table}")

        for user_id in list(self.created_user_ids):
            try:
                response = self._request(
                    "DELETE",
                    f"/auth/v1/admin/users/{user_id}",
                    identity="service",
                )
                if response.status_code not in {200, 404}:
                    self.cleanup_errors.append("auth_user")
            except Exception:
                self.cleanup_errors.append("auth_user")
            finally:
                self.created_user_ids.discard(user_id)

        self.evidence["cleanup"] = {
            "status": "pass" if not self.cleanup_errors else "fail",
            "remaining_tracked_storage_objects": len(self.storage_paths),
            "remaining_tracked_auth_users": len(self.created_user_ids),
            "errors": sorted(set(self.cleanup_errors)),
        }

    def run(self) -> dict[str, Any]:
        owner_email = f"m1-owner-{self.run_id}@example.invalid"
        other_email = f"m1-other-{self.run_id}@example.invalid"
        owner_password = "M1!" + secrets.token_urlsafe(20) + "aA9"
        other_password = "M1!" + secrets.token_urlsafe(20) + "bB8"
        error: Optional[str] = None
        try:
            owner = self._admin_create_user(
                owner_email, owner_password, confirmed=True
            )
            other = self._admin_create_user(
                other_email, other_password, confirmed=True
            )
            owner_id = str(owner["id"])
            other_id = str(other["id"])
            self.check_auth_settings_and_confirmation(
                owner_email, owner_password
            )
            new_password, owner_session = self.check_password_recovery(
                owner_email, owner_password
            )
            other_session = self._sign_in(
                other_email, other_password
            )
            ids = self.seed_rls_fixtures(owner_id, other_id)
            self.check_four_identity_rls(
                ids,
                owner_id,
                str(owner_session["access_token"]),
                str(other_session["access_token"]),
            )
            self.check_storage_four_identity(
                str(owner_session["access_token"]),
                str(other_session["access_token"]),
            )
            self.check_logout_and_delete(
                owner_id,
                owner_email,
                new_password,
                owner_session,
            )
        except Exception as exc:
            error = (
                str(exc)
                if isinstance(exc, AcceptanceError)
                else type(exc).__name__
            )
        finally:
            self.cleanup()
            self.close()

        if error or self.cleanup_errors:
            self.evidence["gate_status"] = "fail"
            self.evidence["error"] = error or "cleanup failed"
        else:
            self.evidence["gate_status"] = "pass"
        return redact_evidence(self.evidence)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run synthetic M1 Auth/RLS/Storage acceptance on staging."
        )
    )
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--base-url", default=STAGING_URL)
    parser.add_argument(
        "--allow-live-staging-writes",
        action="store_true",
        help=(
            "Required acknowledgement for synthetic staging writes and "
            "cleanup."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        base_url = validate_live_target(
            args.project_ref,
            args.base_url,
            args.allow_live_staging_writes,
        )
        anon_key, service_key = _load_legacy_keys(args.project_ref)
        result = StagingM1Acceptance(
            base_url, anon_key, service_key
        ).run()
    except (AcceptanceError, ValueError) as exc:
        result = {
            "target": {
                "project_ref": args.project_ref,
                "environment": "staging",
            },
            "gate_status": "fail",
            "error": str(exc),
            "cleanup": {"status": "not_started"},
        }
    print(
        json.dumps(
            redact_evidence(result),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.get("gate_status") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

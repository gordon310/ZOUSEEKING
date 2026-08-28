"""Parameterized persistence operations for anonymous property intake."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional
from uuid import UUID

import asyncpg

from .completeness import FieldValue
from .geocoding import AddressCandidate
from .models import ConfirmFieldRequest, CreateInputRequest, LocationRequest


class SessionNotFound(Exception):
    """A uniform internal error for missing, expired, or unauthorized sessions."""

    def __init__(self) -> None:
        super().__init__("analysis session not found")


class ProjectNameRequired(Exception):
    """Raised when a converted project has neither an address nor a manual name."""


class DuplicateAddress(Exception):
    """Raised when an owner already has the same address under the default name."""


class ProjectNameTaken(Exception):
    """Raised when an owner already uses the requested project name."""


@dataclass(frozen=True)
class ConvertedProject:
    owner_user_id: UUID
    property_id: UUID


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, default)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _number(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped) if "." in stripped else int(stripped)
        except ValueError:
            return None
    return value


def normalize_address(value: Any) -> str:
    """Normalize address text for owner-scoped duplicate comparisons."""

    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value)).replace("\u3000", " ")
    return re.sub(r"\s+", "", normalized).strip()


def _clean_project_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", str(value)).replace("\u3000", " ")
    return " ".join(normalized.split())[:200]


class IntakeRepository:
    def __init__(self, pool: Any, clock: Any = None) -> None:
        self.pool = pool
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def create_session(
        self,
        purpose: str,
        consent_version: str,
        token_hash: str,
        expires_at: datetime,
    ) -> Any:
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(
                """
                insert into public.analysis_sessions
                  (purpose, consent_version, token_hash, expires_at)
                values ($1, $2, $3, $4)
                returning *
                """,
                purpose,
                consent_version,
                token_hash,
                expires_at,
            )

    async def require_session(self, session_id: UUID, token_hash: str) -> Any:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select *
                from public.analysis_sessions
                where id=$1
                  and token_hash=$2
                  and (status='converted' or expires_at > now())
                """,
                session_id,
                token_hash,
            )
        if not row:
            raise SessionNotFound()
        return row

    async def add_input(
        self,
        session_id: UUID,
        request: CreateInputRequest,
        *,
        storage_path: Optional[str] = None,
        original_name: Optional[str] = None,
        media_type: Optional[str] = None,
        size_bytes: Optional[int] = None,
        content_hash: Optional[str] = None,
    ) -> Any:
        processing_status = "manual_review"
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(
                """
                insert into public.project_inputs
                  (session_id, input_type, source_url, storage_path, original_name,
                   media_type, size_bytes, content_hash, raw_text, processing_status)
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                returning *
                """,
                session_id,
                request.input_type,
                request.source_url,
                storage_path,
                original_name,
                media_type,
                size_bytes,
                content_hash,
                request.raw_text,
                processing_status,
            )

    async def add_file_input(self, session_id: UUID, storage_object: Any) -> Any:
        input_type = "pdf" if storage_object.media_type == "application/pdf" else "image"
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(
                """
                insert into public.project_inputs
                  (session_id, input_type, storage_path, original_name, media_type,
                   size_bytes, content_hash, processing_status)
                values ($1, $2, $3, $4, $5, $6, $7, 'pending')
                returning *
                """,
                session_id,
                input_type,
                storage_object.path,
                storage_object.original_name,
                storage_object.media_type,
                storage_object.size_bytes,
                storage_object.content_hash,
            )

    async def get_fields(self, session_id: UUID) -> Dict[str, FieldValue]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                """
                select pf.field_name, pf.confirmed_value, pf.confirmation_status,
                       pf.selected_evidence_id, coalesce(pfe.confidence, 'unreviewed') as confidence
                from public.project_fields pf
                left join public.project_field_evidence pfe
                  on pfe.id = pf.selected_evidence_id
                where pf.session_id=$1
                """,
                session_id,
            )
        return {
            str(_row_value(row, "field_name")): FieldValue(
                value=_json_value(_row_value(row, "confirmed_value")),
                confirmation_status=str(_row_value(row, "confirmation_status", "unreviewed")),
                confidence=str(_row_value(row, "confidence", "unreviewed")),
                has_evidence=_row_value(row, "selected_evidence_id") is not None,
            )
            for row in rows
        }

    async def upsert_field(self, session_id: UUID, request: ConfirmFieldRequest) -> Any:
        normalized_value = request.value
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                if request.source_input_id:
                    source_input_exists = await connection.fetchval(
                        """
                        select 1
                        from public.project_inputs
                        where id=$1 and session_id=$2
                        """,
                        request.source_input_id,
                        session_id,
                    )
                    if not source_input_exists:
                        raise SessionNotFound()
                evidence = await connection.fetchrow(
                    """
                    insert into public.project_field_evidence
                      (session_id, source_input_id, field_name, raw_value, normalized_value,
                       unit, locator, extraction_method, confidence)
                    values ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, 'manual', 'unreviewed')
                    returning *
                    """,
                    session_id,
                    request.source_input_id,
                    request.field_name,
                    _json_text(request.value),
                    _json_text(normalized_value),
                    request.unit,
                    request.locator,
                )
                evidence_id = _row_value(evidence, "id")
                return await connection.fetchrow(
                    """
                    insert into public.project_fields
                      (session_id, field_name, selected_evidence_id, confirmed_value,
                       unit, confirmation_status, confirmed_at)
                    values ($1, $2, $3, $4::jsonb, $5, $6, now())
                    on conflict (session_id, field_name) do update set
                      selected_evidence_id=excluded.selected_evidence_id,
                      confirmed_value=excluded.confirmed_value,
                      unit=excluded.unit,
                      confirmation_status=excluded.confirmation_status,
                      confirmed_at=excluded.confirmed_at,
                      updated_at=now()
                    returning *
                    """,
                    session_id,
                    request.field_name,
                    evidence_id,
                    _json_text(request.value),
                    request.unit,
                    request.confirmation_status,
                )

    async def save_preview(self, session_id: UUID, preview: Mapping[str, Any]) -> Any:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    insert into public.free_previews
                      (session_id, completeness, acquisition_costs, risk_summary,
                       comparable_status, calculation_version)
                    values ($1, $2::jsonb, $3::jsonb, $4::jsonb, $5, $6)
                    on conflict (session_id) do update set
                      completeness=excluded.completeness,
                      acquisition_costs=excluded.acquisition_costs,
                      risk_summary=excluded.risk_summary,
                      comparable_status=excluded.comparable_status,
                      calculation_version=excluded.calculation_version
                    returning *
                    """,
                    session_id,
                    _json_text(preview["completeness"]),
                    _json_text(preview["acquisition_costs"]),
                    _json_text(preview["risk_summary"]),
                    preview["comparable_status"],
                    preview["calculation_version"],
                )
                await connection.execute(
                    """
                    update public.analysis_sessions
                    set status='preview_ready',
                        purpose_locked_at=coalesce(purpose_locked_at, now()),
                        updated_at=now()
                    where id=$1 and status <> 'converted'
                    """,
                    session_id,
                )
                return row

    async def save_location(
        self,
        session_id: UUID,
        request: LocationRequest,
        candidate: Optional[AddressCandidate],
    ) -> Any:
        address_candidate = candidate.address if candidate else ""
        address_source = candidate.source if candidate else "unavailable"
        address_precision = candidate.precision if candidate else ""
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                update public.analysis_sessions
                set latitude=$2,
                    longitude=$3,
                    location_accuracy_m=$4,
                    location_source=$5,
                    location_captured_at=$6,
                    location_consent_version=$7,
                    address_candidate=$8,
                    address_source=$9,
                    address_precision=$10,
                    updated_at=now()
                where id=$1 and status <> 'converted'
                returning *
                """,
                session_id,
                request.latitude,
                request.longitude,
                request.accuracy_m,
                request.source,
                request.captured_at,
                request.consent_version,
                address_candidate,
                address_source,
                address_precision,
            )
        if not row:
            raise SessionNotFound()
        return row

    async def convert_to_user(
        self,
        session_id: UUID,
        token_hash: str,
        user_id: UUID,
        project_name: Optional[str] = None,
    ) -> ConvertedProject:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                session = await connection.fetchrow(
                    """
                    select *
                    from public.analysis_sessions
                    where id=$1
                      and token_hash=$2
                      and (status='converted' or expires_at > now())
                    for update
                    """,
                    session_id,
                    token_hash,
                )
                if not session:
                    raise SessionNotFound()

                owner_user_id = _row_value(session, "owner_user_id")
                property_id = _row_value(session, "property_id")
                status = _row_value(session, "status")
                if owner_user_id is not None:
                    if status == "converted" and _as_uuid(owner_user_id) == user_id and property_id:
                        return ConvertedProject(user_id, _as_uuid(property_id))
                    raise SessionNotFound()
                if status != "preview_ready":
                    raise SessionNotFound()

                field_rows = await connection.fetch(
                    """
                    select field_name, confirmed_value
                    from public.project_fields
                    where session_id=$1
                    """,
                    session_id,
                )
                values: Dict[str, Any] = {
                    str(_row_value(row, "field_name")): _json_value(_row_value(row, "confirmed_value"))
                    for row in field_rows
                }
                address = _clean_project_name(values.get("address"))
                normalized_address = normalize_address(address)
                manual_name = _clean_project_name(project_name)
                final_name = manual_name or address
                if not final_name:
                    raise ProjectNameRequired()

                is_manual_name = bool(manual_name and normalize_address(manual_name) != normalized_address)
                if normalized_address and not is_manual_name:
                    duplicate_address = await connection.fetchval(
                        """
                        select 1
                        from public.properties
                        where owner_user_id=$1 and address_normalized=$2
                        limit 1
                        """,
                        user_id,
                        normalized_address,
                    )
                    if duplicate_address:
                        raise DuplicateAddress()

                name_taken = await connection.fetchval(
                    """
                    select 1
                    from public.properties
                    where owner_user_id=$1 and project_name=$2
                    limit 1
                    """,
                    user_id,
                    final_name,
                )
                if name_taken:
                    raise ProjectNameTaken()

                try:
                    property_id = await connection.fetchval(
                        """
                        insert into public.properties
                          (owner_user_id, project_type, prefecture, city, ward,
                           address_normalized, building_name, project_name, building_year, area_sqm,
                           asking_price, price_currency, data_class, confidence,
                           latitude, longitude, location_accuracy_m, location_source,
                           location_captured_at, address_source, address_precision)
                        values ($1, 'residential', '大阪府', '大阪市', $2, $3, $4, $5, $6,
                                $7, $8, 'JPY', 'user_submitted', 'unreviewed', $9, $10,
                                $11, $12, $13, $14, $15)
                        returning id
                        """,
                        user_id,
                        values.get("ward") or "",
                        normalized_address,
                        values.get("building_name") or "",
                        final_name,
                        _number(values.get("building_year")),
                        _number(values.get("area_sqm")),
                        _number(values.get("asking_price_jpy")),
                        _row_value(session, "latitude"),
                        _row_value(session, "longitude"),
                        _row_value(session, "location_accuracy_m"),
                        _row_value(session, "location_source", ""),
                        _row_value(session, "location_captured_at"),
                        _row_value(session, "address_source", "manual"),
                        _row_value(session, "address_precision", ""),
                    )
                except asyncpg.UniqueViolationError as exc:
                    raise ProjectNameTaken() from exc
                if not property_id:
                    raise RuntimeError("property conversion failed")
                await connection.execute(
                    """
                    insert into public.residential_details
                      (property_id, management_fee_jpy, repair_reserve_jpy,
                       monthly_rent_jpy, details)
                    values ($1, $2, $3, $4, $5::jsonb)
                    """,
                    property_id,
                    _number(values.get("management_fee_jpy")),
                    _number(values.get("repair_reserve_jpy")),
                    _number(values.get("monthly_rent_jpy")),
                    _json_text({"purpose": _row_value(session, "purpose"), "fields": values}),
                )
                await connection.execute(
                    """
                    update public.analysis_sessions
                    set owner_user_id=$1,
                        property_id=$2,
                        project_name=$3,
                        status='converted',
                        converted_at=now(),
                        updated_at=now()
                    where id=$4
                    """,
                    user_id,
                    property_id,
                    final_name,
                    session_id,
                )
                return ConvertedProject(user_id, _as_uuid(property_id))

    async def get_project(self, property_id: UUID, user_id: UUID) -> Any:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select p.*, rd.management_fee_jpy, rd.repair_reserve_jpy,
                       rd.monthly_rent_jpy, rd.details as residential_details
                from public.properties p
                left join public.residential_details rd on rd.property_id = p.id
                where p.id=$1 and p.owner_user_id=$2
                """,
                property_id,
                user_id,
            )
        if not row:
            raise SessionNotFound()
        return row

    async def consume_rate_limit(
        self,
        abuse_key_hash: str,
        action: str,
        window_started_at: datetime,
        limit: int,
        expires_at: datetime,
    ) -> Optional[int]:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                insert into public.intake_rate_limits
                  (abuse_key_hash, action, window_started_at, request_count, expires_at)
                values ($1, $2, $3, 1, $4)
                on conflict (abuse_key_hash, action, window_started_at) do update set
                  request_count=public.intake_rate_limits.request_count + 1,
                  expires_at=excluded.expires_at
                where public.intake_rate_limits.request_count < $5
                returning request_count
                """,
                abuse_key_hash,
                action,
                window_started_at,
                expires_at,
                limit,
            )
        return int(_row_value(row, "request_count")) if row else None

    async def expire_sessions(self, limit: int = 100) -> List[str]:
        bounded_limit = max(1, min(limit, 100))
        storage_paths: List[str] = []
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                sessions = await connection.fetch(
                    """
                    select id
                    from public.analysis_sessions
                    where status <> 'converted' and expires_at <= now()
                    order by expires_at asc
                    for update skip locked
                    limit $1
                    """,
                    bounded_limit,
                )
                for session in sessions:
                    current_id = _row_value(session, "id")
                    input_rows = await connection.fetch(
                        """
                        select storage_path
                        from public.project_inputs
                        where session_id=$1 and storage_path is not null
                        """,
                        current_id,
                    )
                    storage_paths.extend(
                        str(path)
                        for path in (_row_value(row, "storage_path") for row in input_rows)
                        if path
                    )
                    await connection.execute(
                        """
                        update public.analysis_sessions
                        set status='expired', updated_at=now()
                        where id=$1 and status <> 'converted'
                        """,
                        current_id,
                    )
                await connection.execute(
                    """
                    delete from public.intake_rate_limits
                    where expires_at <= now()
                    """
                )
        return storage_paths

"""Trusted-server adapter for the offline usage ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from .ledger import Ledger, LedgerResult, Scope, UsageKind


OperationRequest = object
ScopeResolver = Callable[[UUID, UsageKind], Scope]
LimitResolver = Callable[[Scope, UsageKind, str], int]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UsageService:
    """Apply usage with identity, scope, and limits resolved by the server."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        scope_resolver: ScopeResolver,
        limit_resolver: LimitResolver,
        clock: Clock = _utc_now,
    ) -> None:
        self.ledger = ledger
        self.scope_resolver = scope_resolver
        self.limit_resolver = limit_resolver
        self.clock = clock

    def apply(self, user_id: UUID, request_key: str, request: OperationRequest) -> LedgerResult:
        scope = self.scope_resolver(user_id, request.kind)
        limit = self.limit_resolver(scope, request.kind, request.period)
        common = {
            "scope": scope,
            "kind": request.kind,
            "units": request.units,
            "limit": limit,
            "request_key": request_key,
            "actor_user_id": user_id,
            "occurred_at": self.clock(),
            "period": request.period,
        }
        if request.operation == "consume":
            return self.ledger.consume(**common)
        if request.operation == "reserve":
            return self.ledger.reserve(**common)
        return getattr(self.ledger, request.operation)(reservation_key=request.reservation_key, **common)

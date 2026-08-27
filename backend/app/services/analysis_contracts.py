"""Typed contracts for versioned metrics, risks, and policy references."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse


SEVERITIES = {"info", "low", "medium", "high", "critical"}
CONFIDENCES = {"high", "medium", "low", "unreviewed"}


@dataclass(frozen=True)
class MetricResult:
    metric_name: str
    value: Decimal | None
    unit: str
    calculation_version: str
    assumption_set: dict[str, Any] = field(default_factory=dict)
    currency: str | None = None

    def __post_init__(self) -> None:
        if not self.metric_name.strip() or not self.unit.strip() or not self.calculation_version.strip():
            raise ValueError("metric name, unit, and calculation version are required")
        if self.value is not None and not isinstance(self.value, Decimal):
            raise TypeError("metric value must be Decimal or None")


@dataclass(frozen=True)
class RiskFinding:
    category: str
    severity: str
    basis: str
    required_evidence: list[str]
    action: str
    confidence: str = "unreviewed"

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unsupported risk severity: {self.severity}")
        if self.confidence not in CONFIDENCES:
            raise ValueError(f"unsupported confidence: {self.confidence}")
        if not self.category.strip() or not self.basis.strip() or not self.action.strip():
            raise ValueError("risk category, basis, and action are required")


@dataclass(frozen=True)
class PolicyDocument:
    policy_id: str
    title: str
    jurisdiction: str
    authority: str
    source_url: str
    effective_from: date
    effective_to: date | None = None
    status: str = "active"

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.policy_id, self.title, self.jurisdiction, self.authority)):
            raise ValueError("policy identity fields are required")
        parsed = urlparse(self.source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("policy source URL must be an absolute http(s) URL")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("policy effective_to cannot precede effective_from")

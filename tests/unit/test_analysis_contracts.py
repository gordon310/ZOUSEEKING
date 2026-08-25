from datetime import date
from decimal import Decimal

import pytest

from backend.app.services.analysis_contracts import MetricResult, PolicyDocument, RiskFinding


def test_metric_requires_unit_and_version():
    with pytest.raises(ValueError):
        MetricResult("net_yield", Decimal("4.2"), "", "v1")
    with pytest.raises(TypeError):
        MetricResult("net_yield", 4.2, "%", "v1")


def test_risk_requires_supported_severity_and_evidence_context():
    risk = RiskFinding("contract", "high", "missing lease", ["lease_contract"], "request contract", "medium")
    assert risk.severity == "high"
    with pytest.raises(ValueError, match="severity"):
        RiskFinding("contract", "urgent", "missing lease", [], "request contract")


def test_policy_requires_valid_source_and_date_range():
    policy = PolicyDocument(
        "takken-35",
        "Important matters",
        "Japan",
        "MLIT",
        "https://www.mlit.go.jp/example",
        date(2026, 1, 1),
    )
    assert policy.status == "active"
    with pytest.raises(ValueError, match="effective_to"):
        PolicyDocument(
            "bad", "Bad", "Japan", "MLIT", "https://example.com", date(2026, 2, 1), date(2026, 1, 1)
        )

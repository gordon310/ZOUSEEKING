from __future__ import annotations

import re

from scripts.verify_report_unlock import (
    READ_ONLY_SQL,
    UnlockContext,
    conclusion_line,
    decide_unlock,
    pooler_dsn,
)


def test_pooler_dsn_removes_query_parameters_without_leaking_credentials() -> None:
    assert pooler_dsn("postgresql://user:secret@example/db?sslmode=require") == (
        "postgresql://user:secret@example/db"
    )


def test_database_audit_contract_is_select_only_and_explicitly_read_only() -> None:
    normalized = " ".join(READ_ONLY_SQL.lower().split())
    assert "select" in normalized
    assert all(not re.search(rf"\\b{word}\\b", normalized) for word in ("insert", "update", "delete", "alter", "create", "drop"))
    assert "payment_orders" in normalized
    assert "payment_events" in normalized
    assert "property_reports" in normalized
    assert "subscriptions" in normalized
    assert "usage_quotas" in normalized
    assert "usage_events" in normalized


def test_paid_report_unlock_requires_matching_payer_report_owner_and_requester() -> None:
    context = UnlockContext(
        order_no="ord_test",
        order_status="paid",
        order_product_code="risk_report_single",
        order_subject_id="report-1",
        order_payer_id="user-a",
        report_key="report-1",
        report_owner_id="user-a",
        requester_id="user-a",
    )

    result = decide_unlock(context)

    assert result.unlocked is True
    assert result.reason == "paid report order and all three identities match"
    assert conclusion_line(result) == "UNLOCK_VERIFIED"


def test_cross_account_cannot_unlock_even_when_order_is_paid() -> None:
    context = UnlockContext(
        order_no="ord_test",
        order_status="paid",
        order_product_code="risk_report_single",
        order_subject_id="report-1",
        order_payer_id="user-a",
        report_key="report-1",
        report_owner_id="user-b",
        requester_id="user-b",
    )

    result = decide_unlock(context)

    assert result.unlocked is False
    assert result.reason == "cross-account cannot unlock: order payer differs from report owner"
    assert conclusion_line(result) == (
        "UNLOCK_FAILED: cross-account cannot unlock: order payer differs from report owner"
    )


def test_report_subject_and_paid_product_are_part_of_unlock_basis() -> None:
    context = UnlockContext(
        order_no="ord_test",
        order_status="paid",
        order_product_code="risk_report_single",
        order_subject_id="other-report",
        order_payer_id="user-a",
        report_key="report-1",
        report_owner_id="user-a",
        requester_id="user-a",
    )

    result = decide_unlock(context)

    assert result.unlocked is False
    assert result.reason == "order subject_id does not match report query_key"


def test_identity_output_redacts_nothing_but_marks_each_match() -> None:
    context = UnlockContext(
        order_no="ord_test",
        order_status="pending",
        order_product_code="risk_report_single",
        order_subject_id="report-1",
        order_payer_id="user-a",
        report_key="report-1",
        report_owner_id="user-b",
        requester_id="user-b",
    )

    result = decide_unlock(context)

    assert result.identity_lines == [
        "订单付款人: user-a",
        "报告 owner: user-b",
        "请求方: user-b",
        "三方匹配: 否",
    ]

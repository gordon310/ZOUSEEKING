#!/usr/bin/env python3
"""Read-only billing unlock audit and historical-order demonstration.

The script never writes to a database. It audits the source contract, runs
local preflight commands, and reads one order through a read-only psql
connection. The final line is deliberately machine-readable:
``UNLOCK_VERIFIED`` or ``UNLOCK_FAILED: <reason>``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Optional


DEFAULT_ORDER_NO = "ord_cs_live_b1PAJXPKYdal2hzFYm5jZD6erEBT3ZwHFHGeUjUy1srPAf8ydwWQCFHUd0"
POOLER_URL_FILE = Path("/tmp/pooler-url.txt")
READ_ONLY_INTENT = "-c default_transaction_read_only=on"

READ_ONLY_SQL = r"""
select json_build_object(
  'order', (
    select json_build_object(
      'order_no', po.order_no,
      'status', po.status,
      'amount_minor', po.amount_minor,
      'currency', po.currency,
      'provider_session_id', po.provider_session_id,
      'provider_payment_intent_id', po.provider_payment_intent_id,
      'paid_at', po.paid_at,
      'owner_user_id', po.owner_user_id,
      'product_code', po.product_code,
      'subject_id', po.subject_id
    )
    from public.payment_orders po
    where po.order_no = __ORDER_NO_LITERAL__
  ),
  'payment_events', coalesce((
    select json_agg(json_build_object(
      'event_type', pe.event_type,
      'status', pe.status,
      'has_provider_event_id', (pe.provider_event_id is not null)
    ) order by pe.created_at, pe.id)
    from public.payment_events pe
    join public.audit_events ae
      on ae.summary->>'event_id' = pe.provider_event_id
     and ae.summary->>'order_upserted' = __ORDER_NO_LITERAL__
  ), '[]'::json),
  'report', (
    select json_build_object(
      'query_key', coalesce(pr.query_key, q.query_key, po.subject_id),
      'report_owner_id', coalesce(pr.owner_user_id, q.owner_user_id),
      'requester_id', q.owner_user_id,
      'report_exists', (pr.id is not null),
      'query_exists', (q.id is not null)
    )
    from public.payment_orders po
    left join public.property_reports pr on pr.query_key = po.subject_id
    left join public.queries q on q.id = pr.query_id
    where po.order_no = __ORDER_NO_LITERAL__
  ),
  'unlock_checks', (
    select json_build_object(
      'paid_order_branch', exists (
        select 1 from public.payment_orders x
        where x.owner_user_id = q.owner_user_id
          and x.product_code = 'risk_report_single'
          and x.subject_id = coalesce(pr.query_key, q.query_key, po.subject_id)
          and x.status = 'paid'
      ),
      'c_plus_quota_branch', exists (
        select 1
        from public.subscriptions s
        join public.usage_quotas uq
          on uq.scope_key = 'user:' || s.user_id::text
         and uq.usage_kind = 'report'
         and uq.period_key = to_char(timezone('Asia/Shanghai', now()), 'YYYY-MM')
        where s.user_id = q.owner_user_id
          and s.product_code = 'c_plus_monthly'
          and s.status in ('active', 'trialing')
          and (s.current_period_end is null or s.current_period_end > now())
          and uq.consumed_units + uq.reserved_units < uq.limit_units
      ),
      'consumed_event_branch', exists (
        select 1 from public.usage_events ue
        where ue.scope_key = 'user:' || q.owner_user_id::text
          and ue.usage_kind = 'report'
          and ue.operation = 'consume'
          and ue.fingerprint = 'c-plus-report:' || coalesce(pr.query_key, q.query_key, po.subject_id)
      ),
      'report_owner_matches_requester', (
        coalesce(pr.owner_user_id, q.owner_user_id) is not null
        and coalesce(pr.owner_user_id, q.owner_user_id) = q.owner_user_id
      ),
      'main_user_report_lookup_found', (pr.id is not null)
    )
    from public.payment_orders po
    left join public.property_reports pr on pr.query_key = po.subject_id
    left join public.queries q on q.id = pr.query_id
    where po.order_no = __ORDER_NO_LITERAL__
  )
)
"""


@dataclass(frozen=True)
class UnlockContext:
    order_no: str
    order_status: Optional[str]
    order_product_code: Optional[str]
    order_subject_id: Optional[str]
    order_payer_id: Optional[str]
    report_key: Optional[str]
    report_owner_id: Optional[str]
    requester_id: Optional[str]


@dataclass(frozen=True)
class UnlockResult:
    unlocked: bool
    reason: str
    identity_lines: list[str]


def _same(*values: Optional[str]) -> bool:
    return bool(values[0]) and all(value == values[0] for value in values[1:])


def decide_unlock(context: UnlockContext) -> UnlockResult:
    """Apply the production unlock basis to a read-only, normalized context."""

    identities_match = _same(
        context.order_payer_id,
        context.report_owner_id,
        context.requester_id,
    )
    identity_lines = [
        f"订单付款人: {context.order_payer_id or '<unavailable>'}",
        f"报告 owner: {context.report_owner_id or '<unavailable>'}",
        f"请求方: {context.requester_id or '<unavailable>'}",
        f"三方匹配: {'是' if identities_match else '否'}",
    ]
    if not context.order_payer_id or not context.report_owner_id or not context.requester_id:
        return UnlockResult(False, "one or more identity IDs are unavailable", identity_lines)
    if not identities_match:
        if context.order_payer_id != context.report_owner_id:
            reason = "cross-account cannot unlock: order payer differs from report owner"
        else:
            reason = "cross-account cannot unlock: requester differs from order payer/report owner"
        return UnlockResult(False, reason, identity_lines)
    if context.order_status != "paid":
        return UnlockResult(False, f"order status is {context.order_status or '<missing>'}, not paid", identity_lines)
    if context.order_product_code != "risk_report_single":
        return UnlockResult(False, "order product_code is not risk_report_single", identity_lines)
    if not context.order_subject_id or context.order_subject_id != context.report_key:
        return UnlockResult(False, "order subject_id does not match report query_key", identity_lines)
    return UnlockResult(True, "paid report order and all three identities match", identity_lines)


def conclusion_line(result: UnlockResult) -> str:
    return "UNLOCK_VERIFIED" if result.unlocked else f"UNLOCK_FAILED: {result.reason}"


@dataclass(frozen=True)
class Evidence:
    label: str
    path: str
    line: int
    snippet: str


def _source_evidence(root: Path, label: str, relative: str, needle: str) -> Evidence:
    path = root / relative
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines, start=1):
        if needle in line:
            return Evidence(label, relative, index, line.strip())
    raise AssertionError(f"missing static evidence: {relative} contains {needle!r}")


def static_audit(root: Path) -> list[Evidence]:
    """Check the six requested contracts and return file/line evidence."""

    checks = [
        ("下单写单号", "backend/app/billing/store.py", 'order_no = f"ord_{session_id}"'),
        ("返回 URL 白名单", "backend/app/billing/routes.py", "def _checkout_return_url"),
        ("webhook 签名", "backend/app/billing/service.py", "construct_event(raw_body, signature_header"),
        ("webhook 幂等", "backend/app/billing/service.py", 'claim.state in {"processed", "dead_letter"}'),
        ("落账字段", "backend/app/billing/store.py", '" (order_no, owner_user_id, organization_id, product_code, price_version,"'),
        ("解锁判定依据", "backend/app/main.py", "async def _has_report_unlock"),
        ("跨账号无法解锁", "backend/app/main.py", "str(owner_user_id) == str(user.user_id)"),
    ]
    return [_source_evidence(root, label, relative, needle) for label, relative, needle in checks]


def _run_command(command: str, cwd: Path) -> tuple[int, str]:
    process = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return process.returncode, process.stdout.strip()


def preflight(root: Path, output: Callable[[str], None]) -> bool:
    py = "backend/.venv/bin/python" if (root / "backend/.venv/bin/python").exists() else "python3"
    commands = [
        "git diff --check",
        f"PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache {py} -m compileall -q scripts backend/app",
    ]
    ok = True
    for command in commands:
        output(f"支付前自检命令: {command}")
        code, text = _run_command(command, root)
        output(f"实际输出 (exit {code}): {text or '<empty>'}")
        ok = ok and code == 0
    return ok


def pooler_dsn(raw_url: str) -> str:
    """Return the libpq URL without query parameters, without logging it."""
    return raw_url.strip().split("?", 1)[0]


def sql_for_order(order_no: str) -> str:
    """Bind the demo order as a SQL literal after escaping it in-process."""
    if "\x00" in order_no:
        raise ValueError("order number contains NUL")
    literal = "'" + order_no.replace("'", "''") + "'"
    return READ_ONLY_SQL.replace("__ORDER_NO_LITERAL__", literal)


def fetch_audit(pooler_file: Path, order_no: str) -> tuple[Optional[dict[str, Any]], str]:
    """Run the audit SELECT under a database-enforced read-only session."""
    try:
        dsn = pooler_dsn(pooler_file.read_text(encoding="utf-8"))
        if not dsn:
            return None, "pooler URL file is empty"
    except OSError:
        return None, "pooler URL file could not be read"

    env = os.environ.copy()
    env["PGOPTIONS"] = READ_ONLY_INTENT
    command = [
        "psql", dsn, "--no-psqlrc", "--quiet", "--tuples-only", "--no-align",
        "--set", "ON_ERROR_STOP=1", "--command", sql_for_order(order_no),
    ]
    process = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if process.returncode != 0:
        return None, f"psql read-only SELECT failed (exit {process.returncode})"
    try:
        return json.loads(process.stdout), "psql read-only SELECT -> matched order"
    except json.JSONDecodeError:
        return None, "psql read-only SELECT returned invalid JSON"


def _context_from_audit(audit: dict[str, Any], args: argparse.Namespace) -> UnlockContext:
    order = audit.get("order") or {}
    report = audit.get("report") or {}
    return UnlockContext(
        order_no=str(order.get("order_no") or args.order_no),
        order_status=order.get("status"),
        order_product_code=order.get("product_code"),
        order_subject_id=order.get("subject_id"),
        order_payer_id=order.get("owner_user_id"),
        report_key=args.report_key or report.get("query_key"),
        report_owner_id=args.report_owner_id or report.get("report_owner_id"),
        requester_id=args.requester_id or report.get("requester_id"),
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--order-no", default=DEFAULT_ORDER_NO)
    parser.add_argument("--pooler-file", type=Path, default=POOLER_URL_FILE)
    parser.add_argument("--report-key")
    parser.add_argument("--report-owner-id")
    parser.add_argument("--requester-id")
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        for evidence in static_audit(root):
            print(f"静态核查[{evidence.label}]: {evidence.path}:{evidence.line}: {evidence.snippet}")
    except (AssertionError, OSError) as exc:
        print(f"静态核查失败: {exc}")
        print(f"UNLOCK_FAILED: static audit failed: {exc}")
        return 1

    preflight_ok = preflight(root, print)
    if not preflight_ok:
        print("UNLOCK_FAILED: payment preflight failed")
        return 1
    if args.skip_live:
        print("UNLOCK_FAILED: live historical-order demo was skipped")
        return 1

    import os

    audit, response_line = fetch_audit(args.pooler_file, args.order_no)
    print(f"真实只读演示: {response_line}")
    if not audit or not audit.get("order"):
        result = UnlockResult(False, "historical order could not be read from the read-only database", [
            "订单付款人: <unavailable>",
            "报告 owner: <unavailable>",
            "请求方: <unavailable>",
            "三方匹配: 否",
        ])
    else:
        order = audit["order"]
        for field in (
            "order_no", "status", "amount_minor", "currency", "provider_session_id",
            "provider_payment_intent_id", "paid_at", "owner_user_id",
        ):
            print(f"订单字段:{field}={order.get(field)}")
        print("payment_events:")
        events = audit.get("payment_events") or []
        if events:
            for event in events:
                print(
                    "  event_type={event_type} status={status} "
                    "has_provider_event_id={has_provider_event_id}".format(**event)
                )
        else:
            print("  <no event associated through audit_events>")
        result = decide_unlock(_context_from_audit(audit, args))
        checks = audit.get("unlock_checks") or {}
        print("解锁判定实际查询结果:")
        for name, value in checks.items():
            print(f"  {name}={value}")
    for line in result.identity_lines:
        print(line)
    print(conclusion_line(result))
    return 0 if result.unlocked else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Validate the pre-production SLO/capacity review contract without network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPORT = "docs/operations/post-launch-slo-review-2026-09-01.json"
REPORT_DOC = "docs/operations/post-launch-slo-review-2026-09-01.md"
ADR = "docs/architecture/adr-0002-render-postgres-future-migration.md"
BASELINE = "docs/operations/staging-capacity-baseline-2026-09-01.json"
REQUIRED_METRICS = {
    "api_slo",
    "error_budget",
    "database_pool",
    "worker_backlog",
    "storage_growth",
    "cost",
}


def _read_json(root: Path, relative: str) -> dict[str, Any]:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def audit(root: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        report = _read_json(root, REPORT)
    except (OSError, json.JSONDecodeError) as exc:
        message = f"cannot load post-launch review: {exc}"
        return {"status": "fail", "errors": [message]}, [message]

    if report.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if report.get("status") != "blocked_pre_production":
        errors.append("status must remain blocked_pre_production until production evidence exists")
    if report.get("production_contacted") is not False:
        errors.append("production_contacted must be false")
    if report.get("customer_content_read") is not False:
        errors.append("customer_content_read must be false")
    if report.get("evidence_window_days") != [30, 60]:
        errors.append("evidence_window_days must be [30, 60]")

    metrics = report.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != REQUIRED_METRICS:
        errors.append("metrics must cover the six required aggregate tracks")
    elif set(metrics.values()) != {"not_available"}:
        errors.append("metrics must remain not_available without production aggregates")

    optimization = report.get("optimization")
    if not isinstance(optimization, dict) or optimization.get("status") != "not_started":
        errors.append("optimization must remain not_started without a profile")

    render = report.get("render_postgres")
    if not isinstance(render, dict):
        errors.append("render_postgres decision is missing")
    else:
        if render.get("decision") != "defer":
            errors.append("render_postgres decision must be defer")
        if render.get("migration_approved") is not False:
            errors.append("render_postgres migration_approved must be false")
        if render.get("live_write_approval") != "required":
            errors.append("live_write_approval must remain required")
        if render.get("production_reset") != "forbidden":
            errors.append("production_reset must remain forbidden")

    for relative in (REPORT_DOC, ADR, BASELINE):
        if not (root / relative).is_file():
            errors.append(f"required evidence file is missing: {relative}")

    try:
        baseline = _read_json(root, BASELINE)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load local baseline: {exc}")
    else:
        if baseline.get("production_contacted") is not False:
            errors.append("local baseline must prove production_contacted=false")

    adr_text = (root / ADR).read_text(encoding="utf-8") if (root / ADR).is_file() else ""
    for marker in (
        "状态：Accepted（暂缓，非迁移批准）",
        "migration_baseline_status = reconciliation_required",
        "live_write_approval=required",
        "production_reset=forbidden",
        "不得更换 `DATABASE_URL`",
        "不得创建 Render PostgreSQL",
        "不得迁移数据",
    ):
        if marker not in adr_text:
            errors.append(f"Render ADR missing safety marker: {marker}")

    result = {
        "status": "pass" if not errors else "fail",
        "review_status": report.get("status"),
        "production_contacted": report.get("production_contacted"),
        "metrics": report.get("metrics"),
        "render_postgres_decision": (report.get("render_postgres") or {}).get("decision"),
        "errors": errors,
    }
    return result, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    args = parser.parse_args(argv)

    result, errors = audit(args.root.resolve())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif errors:
        print("post_launch_review_status=fail")
        for error in errors:
            print(f"- {error}")
    else:
        print(
            "post_launch_review_status=pass "
            f"review_status={result['review_status']} "
            f"render_postgres_decision={result['render_postgres_decision']}"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

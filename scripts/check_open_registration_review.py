#!/usr/bin/env python3
"""Offline consistency review of the open-registration launch posture (countdown D-6).

Zero network, zero socket, zero credentials: every assertion is derived from
repository source and documentation. A passing run proves only that the
*declared* posture is internally consistent in this checkout - it never proves
that a running staging or production environment behaves this way. The live
half of the review (real rate-limit behaviour, real enumeration responses, real
email-confirmation behaviour) is listed in
``docs/release/open-registration-launch-review.md`` as not executed and needs an
environment authorization.

Checks (each one is a repository fact, not a re-statement of an expectation):

C1  ``InviteRegisterRequest.invite_code`` is optional and defaults to "".
C2  ``register_invited_user`` handles the empty invite code before any invite
    table call (the open-registration path cannot touch ``reserve_invite_code``).
C3  The single Admin create-user path sets ``email_confirm=True`` (accounts are
    provisioned pre-confirmed; no confirmation mail is expected from us).
C4  Registration is rate limited through the shared counter and fails closed,
    and the limit key is registered in the production configuration contract.
C5  The consumer sign-up surface never requires an invite code.
C6  The four-language announcement states open registration and marks the trial
    period in every language, with no unfilled placeholder.

Informational finding (never fails the run): the registration endpoint still
answers ``account_already_exists`` for a taken email, which is an enumeration
signal; AGENTS requires uniform responses where enumeration is possible, so the
disposition needs a product/security decision rather than a silent rewrite.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

ROUTE_SOURCE = "backend/app/routes/invites.py"
INVITES_SOURCE = "backend/app/invites.py"
BACKEND_ROOT = "backend/app"
PRODUCTION_CONTRACT = "docs/operations/production-configuration-contract.md"
ENV_EXAMPLE = "deploy/.env.example"
CONSUMER_PAGE = "web/profile.html"
SHARED_PAGE = "web/index.html"
FRONTEND_SOURCE = "web-source/app.js"
ANNOUNCEMENT = "docs/release/launch-announcement-2026-10-07.md"

RATE_LIMIT_KEY = "INVITE_REGISTER_RATE_LIMIT_PER_HOUR"
REGISTRATION_ACTION = "consumer_registration"

# (language label, heading, open-registration token, trial token)
ANNOUNCEMENT_SECTIONS = (
    ("zh-CN", "## 简体中文(zh-CN)", "无需邀请码", "试运行"),
    ("zh-Hant", "## 繁體中文(zh-Hant)", "無需邀請碼", "試營運"),
    ("ja", "## 日本語(ja)", "招待コード不要", "トライアル"),
    ("en", "## English (en)", "no invite code required", "trial"),
)
PLACEHOLDER_TOKENS = ("TBD", "待定", "未定", "TODO", "XXXX")

NOT_EXECUTED = (
    "真实注册限流实测(需要 staging/production 凭据与一次性写入授权)",
    "真实账号枚举响应实测(需要一个受控已注册邮箱)",
    "真实邮件确认行为实测(需要 provider 侧 GoTrue 配置读取权)",
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _field_defaults(tree: ast.Module, class_name: str) -> dict[str, ast.expr | None] | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields: dict[str, ast.expr | None] = {}
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    fields[statement.target.id] = statement.value
            return fields
    return None


def _field_is_optional_empty_default(fields: dict[str, ast.expr | None], name: str) -> tuple[bool, str]:
    value = fields.get(name)
    if value is None:
        return False, f"{name} field is missing from the registration request model"
    if not isinstance(value, ast.Call):
        return False, f"{name} is annotated without a Field(...) default: {ast.unparse(value)}"
    if value.args:
        return False, f"{name} passes a positional Field argument (required marker): {ast.unparse(value)}"
    for keyword in value.keywords:
        if keyword.arg == "default" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "":
            return True, f"{name} = {ast.unparse(value)}"
    return False, f"{name} does not default to an empty string: {ast.unparse(value)}"


def _empty_code_branch_line(tree: ast.Module, function_name: str) -> int | None:
    """Line of the early-returning `invite_code == ""` branch inside a function.

    The open-registration path only stays invite-free if that branch returns
    before any invite-table statement runs, so a branch that does not return is
    not accepted as the guard.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != function_name:
            continue
        for inner in node.body:
            if not isinstance(inner, ast.If):
                continue
            text = ast.unparse(inner.test).replace("'", '"')
            if "invite_code" not in text or '""' not in text:
                continue
            has_return = any(
                isinstance(descendant, ast.Return) for statement in inner.body for descendant in ast.walk(statement)
            )
            if has_return:
                return inner.lineno
    return None


def _first_call_line(tree: ast.Module, needle: str) -> int | None:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            text = ast.unparse(node.func)
            if needle in text:
                lines.append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and needle in node.value:
            lines.append(node.lineno)
    return min(lines) if lines else None


def _dict_values_for_key(tree: ast.Module, key: str) -> list[tuple[int, object]]:
    found: list[tuple[int, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for dict_key, dict_value in zip(node.keys, node.values):
            if isinstance(dict_key, ast.Constant) and dict_key.value == key:
                value = dict_value.value if isinstance(dict_value, ast.Constant) else ast.unparse(dict_value)
                found.append((node.lineno, value))
    return found


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def audit(root: Path) -> tuple[dict[str, Any], list[str]]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    findings: list[str] = []

    def record(check_id: str, ok: bool, detail: str) -> None:
        checks.append({"id": check_id, "ok": ok, "detail": detail})
        if not ok:
            errors.append(f"{check_id}: {detail}")

    # C1 - the registration request model accepts a missing invite code.
    fields = _field_defaults(_parse(root / ROUTE_SOURCE), "InviteRegisterRequest")
    if fields is None:
        record("C1_registration_request_optional_invite_code", False, "InviteRegisterRequest model not found")
    else:
        ok, detail = _field_is_optional_empty_default(fields, "invite_code")
        record("C1_registration_request_optional_invite_code", ok, detail)

    # C2 - the no-invite branch runs before any invite table statement.
    invites_tree = _parse(root / INVITES_SOURCE)
    branch_line = _empty_code_branch_line(invites_tree, "register_invited_user")
    reserve_line = _first_call_line(invites_tree, "reserve_invite_code")
    if branch_line is None:
        record("C2_open_registration_skips_invite_tables", False, "no empty-invite-code branch in register_invited_user")
    elif reserve_line is None:
        record("C2_open_registration_skips_invite_tables", False, "reserve_invite_code call not found (invite path may be gone)")
    elif branch_line < reserve_line:
        record(
            "C2_open_registration_skips_invite_tables",
            True,
            f"empty-code branch at line {branch_line} precedes the invite reservation at line {reserve_line}",
        )
    else:
        record(
            "C2_open_registration_skips_invite_tables",
            False,
            f"invite reservation (line {reserve_line}) is reached before the empty-code branch (line {branch_line})",
        )

    # C3 - email confirmation behaviour is defined and the create path is unique.
    confirmations = _dict_values_for_key(invites_tree, "email_confirm")
    confirmation_ok = bool(confirmations) and all(value is True for _, value in confirmations)
    create_paths = [
        path.relative_to(root).as_posix()
        for path in sorted((root / BACKEND_ROOT).rglob("*.py"))
        if "/auth/v1/admin/users" in path.read_text(encoding="utf-8", errors="replace")
        and "admin/users/{user_id}" not in path.read_text(encoding="utf-8", errors="replace")
    ]
    if not confirmation_ok:
        record(
            "C3_admin_create_pre_confirms_email",
            False,
            f"email_confirm payload values are {confirmations or 'absent'}",
        )
    elif create_paths != [INVITES_SOURCE]:
        record(
            "C3_admin_create_pre_confirms_email",
            False,
            f"admin user creation is not owned by a single module: {create_paths}",
        )
    else:
        record(
            "C3_admin_create_pre_confirms_email",
            True,
            f"email_confirm=True at line {confirmations[0][0]}; the only admin create path is {create_paths[0]}",
        )

    # C4 - shared, failing-closed rate limit plus a registered limit key.
    route_text = _read(root, ROUTE_SOURCE)
    limit_gaps = [
        token
        for token in (
            "consume_shared_rate_limit",
            REGISTRATION_ACTION,
            "rate_limited",
            "RateLimitStoreUnavailable",
            "rate_limit_unavailable",
        )
        if token not in route_text
    ]
    contract_text = _read(root, PRODUCTION_CONTRACT)
    env_text = _read(root, ENV_EXAMPLE)
    if limit_gaps:
        record("C4_registration_rate_limit_fails_closed", False, f"registration route is missing: {', '.join(limit_gaps)}")
    elif RATE_LIMIT_KEY not in contract_text or RATE_LIMIT_KEY not in env_text:
        record(
            "C4_registration_rate_limit_fails_closed",
            False,
            f"{RATE_LIMIT_KEY} is not registered in both the production contract and deploy/.env.example",
        )
    else:
        record(
            "C4_registration_rate_limit_fails_closed",
            True,
            f"shared counter scope '{REGISTRATION_ACTION}' with fail-closed 503; {RATE_LIMIT_KEY} registered",
        )

    # C5 - the consumer sign-up surface never requires an invite code.
    consumer_page = _read(root, CONSUMER_PAGE)
    shared_page = _read(root, SHARED_PAGE)
    frontend_source = _read(root, FRONTEND_SOURCE)
    surface_gaps: list[str] = []
    if "registerInviteCode" in consumer_page:
        surface_gaps.append(f"{CONSUMER_PAGE} exposes an invite-code field on the consumer sign-up page")
    if "registerInviteCode" in shared_page:
        for line in shared_page.splitlines():
            if "registerInviteCode" in line and "required" in line:
                surface_gaps.append(f"{SHARED_PAGE} marks the invite-code field required")
    if '$("#registerInviteCode")?.value' not in frontend_source:
        surface_gaps.append(f"{FRONTEND_SOURCE} does not read the invite-code field defensively")
    if surface_gaps:
        record("C5_consumer_signup_never_requires_invite_code", False, "; ".join(surface_gaps))
    else:
        record(
            "C5_consumer_signup_never_requires_invite_code",
            True,
            f"{CONSUMER_PAGE} has no invite-code field; {SHARED_PAGE} keeps it optional; the reader stays null-safe",
        )

    # C6 - four-language announcement alignment.
    announcement = _read(root, ANNOUNCEMENT)
    sections: dict[str, str] = {}
    for label, heading, _, _ in ANNOUNCEMENT_SECTIONS:
        start = announcement.find(heading)
        sections[label] = announcement[start:] if start >= 0 else ""
    announcement_gaps: list[str] = []
    for label, heading, open_token, trial_token in ANNOUNCEMENT_SECTIONS:
        body = sections[label]
        if not body:
            announcement_gaps.append(f"{label}: section heading '{heading}' is missing")
            continue
        if open_token not in body:
            announcement_gaps.append(f"{label}: open-registration wording '{open_token}' is missing")
        if trial_token not in body:
            announcement_gaps.append(f"{label}: trial-period marker '{trial_token}' is missing")
    placeholders = [token for token in PLACEHOLDER_TOKENS if token in announcement]
    if placeholders:
        announcement_gaps.append(f"unfilled placeholders present: {', '.join(placeholders)}")
    if announcement_gaps:
        record("C6_four_language_open_registration_alignment", False, "; ".join(announcement_gaps))
    else:
        record(
            "C6_four_language_open_registration_alignment",
            True,
            "zh-CN / zh-Hant / ja / en each state open registration and mark the trial period; no placeholders",
        )

    # Informational: enumeration signal on registration.
    if "account_already_exists" in _read(root, INVITES_SOURCE):
        findings.append(
            "registration answers 'account_already_exists' (HTTP 409) for a taken email, so sign-up reveals "
            "whether an account exists; AGENTS asks for uniform responses where enumeration is possible - "
            "disposition is a product/security decision, see the review document"
        )

    result = {
        "schema_version": 1,
        "scope": "open_registration_offline_review",
        "status": "pass" if not errors else "fail",
        "production_contacted": False,
        "network_used": False,
        "checks": checks,
        "findings": findings,
        "not_executed": list(NOT_EXECUTED),
        "errors": errors,
    }
    return result, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
        print("open_registration_review_status=fail")
        for error in errors:
            print(f"- {error}")
        for finding in result["findings"]:
            print(f"! finding: {finding}")
    else:
        print(f"open_registration_review_status=pass checks={len(result['checks'])}")
        for check in result["checks"]:
            print(f"- {check['id']}: {check['detail']}")
        for finding in result["findings"]:
            print(f"! finding: {finding}")
        print("not executed (needs an environment authorization): " + "; ".join(result["not_executed"]))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

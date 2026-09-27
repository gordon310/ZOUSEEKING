from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "collect_first_week_observation.py"


def load_collector():
    spec = importlib.util.spec_from_file_location("first_week_collector", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_contract(path: Path, metrics: list[dict]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact": "first-week-observation-dashboard",
                "domains": [{"id": "test", "metrics": metrics}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def query_metric(metric_id: str, sql: str = "select 1 as value") -> dict:
    return {
        "id": metric_id,
        "query": sql,
        "windows": ["first_week"],
        "threshold": "literal threshold",
        "owner": "test owner",
    }


def command_metric(metric_id: str, command: str) -> dict:
    return {
        "id": metric_id,
        "command": command,
        "windows": ["first_week"],
        "threshold": "literal threshold",
        "owner": "test owner",
    }


def test_plan_is_default_and_never_starts_subprocess(monkeypatch, capsys) -> None:
    collector = load_collector()

    def forbidden(*args, **kwargs):
        raise AssertionError("--plan must not run subprocesses")

    monkeypatch.setattr(collector.subprocess, "run", forbidden)
    assert collector.main([]) == 0
    assert "mlit_quarter_freshness" in capsys.readouterr().out


@pytest.mark.parametrize(
    "sql",
    [
        "select 1; update public.rows set value = 2",
        "select 1; insert into public.rows values (1)",
        "select 1; drop table public.rows",
        "select 1 as one; select 2 as two",
    ],
)
def test_sql_guard_rejects_writes_and_multiple_statements(sql: str) -> None:
    collector = load_collector()
    accepted, reason = collector.validate_read_only_sql(sql)
    assert not accepted
    assert reason


def test_sql_guard_uses_keyword_boundaries() -> None:
    collector = load_collector()
    assert collector.validate_read_only_sql("select updated_at as updateable_value from public.rows") == (True, None)


def test_execute_requires_database_url_and_double_opt_in(monkeypatch) -> None:
    collector = load_collector()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as missing_url:
        collector.main(["--execute", "--allow-read-only"])
    assert missing_url.value.code == 2
    monkeypatch.setenv("DATABASE_URL", "postgresql://safe@example.invalid/db")
    with pytest.raises(SystemExit) as missing_switch:
        collector.main(["--execute"])
    assert missing_switch.value.code == 2


def test_untrusted_contract_command_is_rejected_without_execution(tmp_path: Path, monkeypatch) -> None:
    collector = load_collector()
    contract = write_contract(tmp_path / "contract.json", [command_metric("other", "rm -rf /tmp/x")])
    output = tmp_path / "report.json"

    def forbidden(*args, **kwargs):
        raise AssertionError("untrusted command must not execute")

    monkeypatch.setattr(collector.subprocess, "run", forbidden)
    assert collector.main(["--execute", "--allow-read-only", "--database-url", "postgresql://safe@example.invalid/db", "--contract", str(contract), "--output", str(output)]) == 1
    metric = json.loads(output.read_text(encoding="utf-8"))["metrics"][0]
    assert metric["status"] == "failed"
    assert metric["reason"] == "command_not_in_contract"


def test_command_without_available_channel_is_not_collected_and_other_query_is_measured(tmp_path: Path, monkeypatch) -> None:
    collector = load_collector()
    contract = write_contract(
        tmp_path / "contract.json",
        [query_metric("ordinary_query"), command_metric("ordinary_command", "deploy/observability-check.sh")],
    )
    output = tmp_path / "report.json"

    class Result:
        returncode = 0
        stdout = "1\n"
        stderr = ""

    monkeypatch.setattr(collector.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(collector, "command_is_available", lambda args: False)
    assert collector.main(["--execute", "--allow-read-only", "--database-url", "postgresql://safe@example.invalid/db", "--contract", str(contract), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["totals"] == {"measured": 1, "not_collected": 1, "failed": 0}
    assert report["metrics"][0]["status"] == "measured"
    assert report["metrics"][1]["status"] == "not_collected"
    assert report["metrics"][1]["reason"] == "command_unavailable"


@pytest.mark.parametrize(
    ("metric_id", "stdout", "returncode", "expected"),
    [
        ("readiness_probe", "ready\n", 0, "ok"),
        ("backup_freshness", "OBSERVABILITY_OK services=4\n", 0, "ok"),
        ("backup_freshness", "OBSERVABILITY_ALERT backup_age_hours=99\n", 0, "breach"),
        ("worker_liveness", "api\nreport-worker\nworker\nnginx\n", 0, "ok"),
        ("worker_liveness", "api\nreport-worker\nnginx\n", 0, "breach"),
        ("publish_gate_violations", '{"non_synthetic_violations":["x"],"canonical_sha256":"a","web_sha256":"a"}\n', 0, "breach"),
    ],
)
def test_mechanical_verdicts(metric_id: str, stdout: str, returncode: int, expected: str) -> None:
    collector = load_collector()
    assert collector.command_verdict(metric_id, stdout, returncode) == expected


def test_other_metrics_are_manual_review_and_threshold_is_verbatim() -> None:
    collector = load_collector()
    for metric_id in ("structured_error_lines", "mlit_quarter_freshness"):
        assert collector.command_verdict(metric_id, "anything", 0) == "manual_review"
    assert collector.metric_record({**query_metric("sample"), "threshold": "逐字 不改"}, "test")["threshold"] == "逐字 不改"


def test_pii_columns_are_dropped_individually() -> None:
    collector = load_collector()
    for forbidden in collector.PII_COLUMN_SUBSTRINGS:
        value, dropped, truncated, rows, rows_total, rows_truncated = collector.parse_query_value("select 1 as %s" % forbidden, "value\n")
        assert forbidden not in value
        assert forbidden in dropped
        assert not truncated
        assert rows == [{}]
        assert rows_total == 1
        assert not rows_truncated


def test_query_values_preserve_all_rows_and_first_row_value() -> None:
    collector = load_collector()
    value, dropped, truncated, rows, rows_total, rows_truncated = collector.parse_query_value(
        "select 1 as alpha, 2 as beta, 3 as gamma",
        "a|b|c\nd|e|f\ng|h|i\n",
    )
    assert rows == [
        {"alpha": "a", "beta": "b", "gamma": "c"},
        {"alpha": "d", "beta": "e", "gamma": "f"},
        {"alpha": "g", "beta": "h", "gamma": "i"},
    ]
    assert value == rows[0]
    assert dropped == []
    assert not truncated
    assert rows_total == 3
    assert not rows_truncated


def test_query_values_limit_rows_and_report_truncation() -> None:
    collector = load_collector()
    stdout = "\n".join("value-%d" % number for number in range(25))
    _, _, _, rows, rows_total, rows_truncated = collector.parse_query_value(
        "select 1 as value",
        stdout,
    )
    assert len(rows) == 20
    assert rows_total == 25
    assert rows_truncated is True


def test_query_rows_drop_pii_columns_for_every_row() -> None:
    collector = load_collector()
    stdout = "\n".join("user-%d|value-%d" % (number, number) for number in range(25))
    _, dropped, _, rows, _, _ = collector.parse_query_value(
        "select 1 as user_id, 2 as value",
        stdout,
    )
    assert dropped == ["user_id"]
    assert len(rows) == 20
    assert all("user_id" not in row for row in rows)


def test_curl_user_agent_default_ignores_first_week_environment_value(tmp_path: Path, monkeypatch) -> None:
    collector = load_collector()
    contract = write_contract(tmp_path / "contract.json", [command_metric("curl_metric", "curl https://example.invalid")])
    output = tmp_path / "report.json"
    observed = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setenv("FIRST_WEEK_CURL_UA", "environment-specific-agent")
    monkeypatch.setattr(collector, "trusted_commands", lambda: {"curl https://example.invalid"})
    monkeypatch.setattr(collector, "command_is_available", lambda args: True)
    monkeypatch.setattr(collector, "add_curl_user_agent", lambda args, user_agent: observed.append(user_agent) or args)
    monkeypatch.setattr(collector.subprocess, "run", lambda *args, **kwargs: Result())
    assert collector.main(["--execute", "--allow-read-only", "--database-url", "postgresql://safe@example.invalid/db", "--contract", str(contract), "--output", str(output)]) == 0
    assert observed == [collector.DEFAULT_UA]


def test_output_under_repository_docs_is_rejected(monkeypatch) -> None:
    collector = load_collector()
    with pytest.raises(SystemExit) as rejected:
        collector.main(["--output", str(ROOT / "docs" / "first-week-result.json")])
    assert rejected.value.code == 2


def test_command_output_is_limited_to_twenty_lines() -> None:
    collector = load_collector()
    value = collector.parse_command_value("\n".join("line-%d" % number for number in range(25)))
    assert value["stdout_lines"] == ["line-%d" % number for number in range(20)]
    assert value["stdout_lines_total"] == 25

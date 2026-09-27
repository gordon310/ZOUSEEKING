from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from scripts.check_first_week_observation import validate_dashboard


ROOT = Path(__file__).resolve().parents[2]
REAL_JSON = Path(os.environ.get("FIRST_WEEK_OBSERVATION_JSON", ROOT / "docs/operations/first-week-observation-dashboard.json"))
REAL_MARKDOWN = Path(os.environ.get("FIRST_WEEK_OBSERVATION_MARKDOWN", ROOT / "docs/operations/first-week-observation-dashboard.md"))


def _valid_dashboard() -> dict[str, object]:
    return {
        "windows": [{"id": "first_hour"}],
        "domains": [
            {
                "id": "data",
                "metrics": [
                    {
                        "id": "healthy_metric",
                        "metric": "Healthy metric",
                        "source": "public.aggregate_metrics",
                        "query": " select count(*) from public.aggregate_metrics",
                        "unit": "rows",
                        "threshold": "0",
                        "healthy_state": "healthy",
                        "degraded_action": "investigate",
                        "owner": "operations",
                        "windows": ["first_hour"],
                    }
                ],
            }
        ],
    }


def _write_fixture(tmp_path: Path, dashboard: dict[str, object], markdown: str) -> tuple[Path, Path]:
    json_path = tmp_path / "dashboard.json"
    markdown_path = tmp_path / "dashboard.md"
    json_path.write_text(json.dumps(dashboard, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    return json_path, markdown_path


def test_current_dashboard_passes_its_observation_contract() -> None:
    assert validate_dashboard(REAL_JSON, REAL_MARKDOWN) == []


def test_command_only_metric_is_allowed_without_a_query(tmp_path: Path) -> None:
    dashboard = _valid_dashboard()
    metric = dashboard["domains"][0]["metrics"][0]  # type: ignore[index]
    metric.pop("query")  # type: ignore[union-attr]
    metric["command"] = "docker compose -f deploy/docker-compose.prod.yml ps"  # type: ignore[index]
    json_path, markdown_path = _write_fixture(
        tmp_path,
        dashboard,
        "# 上线首周观察看板\n\nproduction_contacted = false\n",
    )

    assert validate_dashboard(json_path, markdown_path) == []


def test_metric_without_query_or_command_is_named_as_missing_observation_probe(tmp_path: Path) -> None:
    dashboard = _valid_dashboard()
    metric = dashboard["domains"][0]["metrics"][0]  # type: ignore[index]
    metric.pop("query")  # type: ignore[union-attr]
    json_path, markdown_path = _write_fixture(
        tmp_path,
        dashboard,
        "# 上线首周观察看板\n\nproduction_contacted = false\n",
    )

    violations = validate_dashboard(json_path, markdown_path)

    assert "metric healthy_metric: missing required observation probe 'query' or 'command'" in violations


@pytest.mark.parametrize(
    ("change", "expected_reasons"),
    [
        (
            lambda metric: metric.update(query="update public.aggregate_metrics set value = 1"),
            ("query must start with select", "prohibited SQL keyword 'update'"),
        ),
        (
            lambda metric: metric.update(query="select 1 into observation_shadow"),
            ("prohibited SQL keyword 'into'",),
        ),
        (lambda metric: metric.update(query="select email from public.aggregate_metrics"), ("PII field 'email'",)),
        (lambda metric: metric.update(source="public.requested_by_email"), ("PII field 'email' in source",)),
        (lambda metric: metric.update(command="update observation_snapshot set value = 1"), ("command contains prohibited write keyword 'update'",)),
        (lambda metric: metric.pop("owner"), ("missing required field 'owner'",)),
        (lambda metric: metric.update(windows=["unknown_window"]), ("unknown window 'unknown_window'",)),
        (lambda metric: metric.update(metric="保证准确的指标"), ("prohibited exaggeration '保证准确'",)),
    ],
)
def test_metric_violations_name_the_affected_metric(
    tmp_path: Path, change: object, expected_reasons: tuple[str, ...]
) -> None:
    dashboard = copy.deepcopy(_valid_dashboard())
    metric = dashboard["domains"][0]["metrics"][0]  # type: ignore[index]
    change(metric)  # type: ignore[operator]
    json_path, markdown_path = _write_fixture(
        tmp_path,
        dashboard,
        "# 上线首周观察看板\n\nproduction_contacted = false\n",
    )

    violations = validate_dashboard(json_path, markdown_path)

    for expected_reason in expected_reasons:
        assert any("metric healthy_metric:" in violation and expected_reason in violation for violation in violations)


def test_markdown_exaggeration_is_reported(tmp_path: Path) -> None:
    json_path, markdown_path = _write_fixture(
        tmp_path,
        _valid_dashboard(),
        "# 上线首周观察看板\n\nproduction_contacted = false\n\n这是稳赚承诺。\n",
    )

    violations = validate_dashboard(json_path, markdown_path)

    assert "document: prohibited exaggeration '稳赚'" in violations


def test_prohibited_exaggeration_in_prohibitive_context_is_allowed(tmp_path: Path) -> None:
    json_path, markdown_path = _write_fixture(
        tmp_path,
        _valid_dashboard(),
        "# 上线首周观察看板\n\nproduction_contacted = false\n\n不得呈现为实时行情。\n",
    )

    assert validate_dashboard(json_path, markdown_path) == []


def test_prohibited_exaggeration_in_affirmative_context_is_reported(tmp_path: Path) -> None:
    json_path, markdown_path = _write_fixture(
        tmp_path,
        _valid_dashboard(),
        "# 上线首周观察看板\n\nproduction_contacted = false\n\n页面展示实时行情。\n",
    )

    violations = validate_dashboard(json_path, markdown_path)

    assert "document: prohibited exaggeration '实时行情'" in violations

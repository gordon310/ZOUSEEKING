import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "staging_synthetic_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("staging_synthetic_smoke", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_plan_never_opens_a_socket(monkeypatch, capsys):
    module = _load_module()

    def no_socket(*args, **kwargs):
        raise AssertionError("plan mode must not create a socket")

    monkeypatch.setattr(socket, "socket", no_socket)
    assert module.main(["--plan"]) == 0
    assert "synthetic" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--execute", "--allow-staging"], "--authorized-writes"),
        (["--plan", "--api-url", "https://zoubeacon.app"], "production host"),
        (["--plan", "--api-url", "https://not-allowed.invalid"], "allowlist"),
        (["--plan", "--project-ref", "wrong-project"], "project-ref"),
        (["--plan", "--candidate-commit", "not-hex"], "40-character hexadecimal"),
        (["--plan", "--candidate-commit", "0" * 40], "does not name a local commit"),
    ],
)
def test_rejects_unsafe_or_invalid_arguments(arguments, message, capsys):
    module = _load_module()
    assert module.main(arguments) == 2
    assert message.lower() in capsys.readouterr().err.lower()


def test_self_check_without_evidence_out_preserves_canonical_evidence(capsys):
    module = _load_module()
    canonical_path = ROOT / "docs" / "release" / "phase-one-staging-evidence.json"
    before = canonical_path.read_bytes()

    assert module.main(["--self-check"]) == 0

    assert canonical_path.read_bytes() == before
    assert '"environment": "offline_self_check"' in capsys.readouterr().out


def test_self_check_writes_redacted_complete_evidence_when_explicitly_requested(tmp_path, capsys):
    module = _load_module()
    evidence_path = tmp_path / "evidence.json"

    assert module.main(["--self-check", "--evidence-out", str(evidence_path)]) == 0
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert evidence["status"] == "pass"
    assert evidence["environment"] == "offline_self_check"
    assert {case["id"] for case in evidence["cases"]} == set(module.CASE_IDS)
    assert all({"id", "description", "status", "expected", "observed", "http_status", "payload_sha256"} <= set(case) for case in evidence["cases"])
    assert evidence["storage_cleanup"]["verified"] is True
    serialized = json.dumps(evidence)
    assert "sb_" not in serialized
    assert "eyJ" not in serialized
    assert "@example.invalid" not in serialized
    assert "access_token" not in serialized
    assert "self-check" in capsys.readouterr().out.lower()


def test_self_check_cannot_write_canonical_evidence(capsys):
    module = _load_module()
    canonical_path = ROOT / "docs" / "release" / "phase-one-staging-evidence.json"
    before = canonical_path.read_bytes()

    assert module.main(["--self-check", "--evidence-out", str(canonical_path)]) == 2

    assert canonical_path.read_bytes() == before
    assert "canonical" in capsys.readouterr().err.lower()


def test_preview_with_real_free_preview_shape_and_no_market_reference_is_safe():
    module = _load_module()
    payload = {
        "completeness": {"identity": {"status": "insufficient_data"}},
        "acquisition_costs": {"status": "insufficient_input"},
        "risk_summary": {},
        "comparable_status": "not_checked",
        "comparable": {"status": "not_checked", "note": "", "reference": []},
        "calculation_version": "free-preview-v1",
    }

    assert module._preview_is_safe(payload) is True


def test_preview_with_sufficient_comparables_requires_data_class_on_every_reference():
    module = _load_module()
    payload = {
        "completeness": {"identity": {"status": "complete"}},
        "acquisition_costs": {"status": "estimated"},
        "comparable_status": "sufficient",
        "comparable": {"status": "sufficient", "note": "", "reference": [{"median_price_jpy": 100}]},
    }

    assert module._preview_is_safe(payload) is False


def test_preview_with_unknown_comparable_status_is_unsafe():
    module = _load_module()
    payload = {
        "completeness": {"identity": {"status": "partial"}},
        "acquisition_costs": {"status": "insufficient_input"},
        "comparable_status": "bogus",
        "comparable": {"status": "bogus", "note": "", "reference": []},
    }

    assert module._preview_is_safe(payload) is False


def test_failure_still_runs_cleanup_and_marks_evidence_failed(tmp_path):
    module = _load_module()
    config = module.default_config()
    transport = module.FakeTransport(config.frontend_version, fail_case="pdf_upload")
    evidence = module.run_smoke(config, transport=transport, environment="offline_test")

    assert evidence["status"] == "fail"
    assert evidence["storage_cleanup"]["attempted"] is True
    assert transport.cleanup_called is True
    assert next(case for case in evidence["cases"] if case["id"] == "pdf_upload")["status"] == "fail"


def test_nonzero_cleanup_residue_fails_verification():
    module = _load_module()
    config = module.default_config()
    transport = module.FakeTransport(config.frontend_version, objects_remaining=1)
    evidence = module.run_smoke(config, transport=transport, environment="offline_test")

    assert evidence["status"] == "fail"
    assert evidence["storage_cleanup"]["objects_remaining"] == 1
    assert evidence["storage_cleanup"]["verified"] is False

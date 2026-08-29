from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_jphouse_worker as worker


def test_claim_pending_job_uses_conditional_update(monkeypatch):
    calls = []

    def fake_request_json(path, method="GET", payload=None, prefer="return=representation"):
        calls.append((path, method, payload, prefer))
        return [{"id": "job-1", "status": "running"}]

    monkeypatch.setattr(worker, "request_json", fake_request_json)

    assert worker.claim_pending_job("job-1") == {"id": "job-1", "status": "running"}
    assert calls == [
        (
            "/generation_jobs?id=eq.job-1&status=eq.pending",
            "PATCH",
            {"status": "running", "progress": 20, "current_step": "JPHOUSE 正在生成报告"},
            "return=representation",
        )
    ]


def test_process_job_skips_when_another_worker_claimed_it(monkeypatch):
    monkeypatch.setattr(worker, "claim_pending_job", lambda _job_id: None)

    def unexpected_update(*args, **kwargs):
        raise AssertionError("a job that was not claimed must not be processed")

    monkeypatch.setattr(worker, "update_row", unexpected_update)

    result = worker.process_job(
        {
            "id": "job-1",
            "queries": {
                "id": "query-1",
                "prefecture": "大阪府",
                "city": "大阪市",
                "ward": "北区",
                "asset_type": "塔楼",
                "year": 2026,
                "month": 8,
            },
        }
    )

    assert result == {"job_id": "job-1", "status": "skipped", "reason": "already_claimed"}

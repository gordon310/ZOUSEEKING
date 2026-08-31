import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "release" / "worktree-integration-manifest.json"


def test_release_manifest_covers_all_candidates_once():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    candidates = manifest["candidates"]
    ids = [item["id"] for item in candidates]
    expected = [f"P0-{index}" for index in range(1, 11)]
    expected += [f"P1-{index}" for index in range(1, 7)]
    expected += [f"P2-{index}" for index in range(1, 4)]
    expected.append("renovation")

    assert ids == expected
    assert len(ids) == len(set(ids))
    assert manifest["release_branch"] == "codex/release-candidate"
    assert set(manifest["rules"]["dispositions"]) == {"integrated", "deferred", "rejected"}


def test_manifest_has_no_machine_paths_or_secrets():
    raw = MANIFEST.read_text(encoding="utf-8")
    assert "/Users/" not in raw
    assert "/private/" not in raw
    lowered = raw.lower()
    assert ".env" not in lowered
    assert "service_role" not in lowered
    assert "secret_key" not in lowered
    assert "sk_live_" not in lowered
    assert "password=" not in lowered


def test_integrated_candidates_identify_a_reviewed_ref():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    integrated = [item for item in manifest["candidates"] if item["disposition"] == "integrated"]
    assert integrated
    for item in integrated:
        assert item["integrated_ref"]
        assert item["target_paths"]

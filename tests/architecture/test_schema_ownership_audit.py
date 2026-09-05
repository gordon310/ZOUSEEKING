from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = ROOT / "scripts/check_schema_ownership.py"


class SchemaOwnershipAuditTest(unittest.TestCase):
    def run_audit(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(AUDIT_SCRIPT), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_repository_audit_reports_one_forward_history(self) -> None:
        result = self.run_audit("--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["canonical_forward_history"], "supabase/migrations")
        self.assertEqual(
            report["migration_baseline_status"],
            "canonical_staging_reconciled_production_pending",
        )
        self.assertEqual(len(report["forward_migration_files"]), 21)
        self.assertEqual(len(report["legacy_sql_files"]), 8)
        self.assertEqual(report["errors"], [])

    def test_npm_command_runs_the_same_offline_audit(self) -> None:
        result = subprocess.run(
            ["npm", "run", "check:schema-ownership", "--", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"status": "pass"', result.stdout)


if __name__ == "__main__":
    unittest.main()

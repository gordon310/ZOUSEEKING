from pathlib import Path

from tests.support.pg_bootstrap import discover_migrations


def test_bootstrap_scans_every_repository_migration() -> None:
    migrations_dir = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

    expected = tuple(sorted(migrations_dir.glob("*.sql")))

    assert discover_migrations(migrations_dir) == expected

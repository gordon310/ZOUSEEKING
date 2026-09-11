from pathlib import Path


def test_analysis_sql_uses_owner_scope_and_enum_text_cast() -> None:
    source = Path("backend/app/analysis/routes.py").read_text(encoding="utf-8")
    assert "q.owner_user_id=$1" in source
    assert "pr.data_class::text" in source
    assert "synthetic_fixture" not in source
    assert "amount_yen" in source
    assert "amount_jpy" not in source


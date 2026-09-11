from datetime import datetime, timezone

from backend.app.member.routes import _period


def test_member_read_period_switches_at_utc_plus_8_midnight() -> None:
    before = _period(datetime(2026, 8, 31, 15, 59, 59, tzinfo=timezone.utc))
    after = _period(datetime(2026, 8, 31, 16, 0, 0, tzinfo=timezone.utc))

    assert before[0] == "2026-08"
    assert after[0] == "2026-09"
    assert before[1].astimezone(timezone.utc).isoformat() == "2026-07-31T16:00:00+00:00"
    assert after[1].astimezone(timezone.utc).isoformat() == "2026-08-31T16:00:00+00:00"

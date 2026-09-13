from backend.app.main import report_status_for_report


def test_report_status_is_terminal_for_collected_and_empty_reports():
    assert report_status_for_report(has_snapshot=True) == "full_report"
    assert report_status_for_report(has_snapshot=False) == "insufficient_data"

from backend.app.main import (
    JPHOUSE_MARKET_SOURCE_ID,
    report_status_for_report,
    source_id_for_report,
)


def test_report_status_is_terminal_for_collected_and_empty_reports():
    assert report_status_for_report(has_snapshot=True) == "full_report"
    assert report_status_for_report(has_snapshot=False) == "insufficient_data"


def test_published_scraped_report_uses_registered_market_source():
    assert source_id_for_report(report_status="full_report", data_class="scraped_aggregate") == JPHOUSE_MARKET_SOURCE_ID
    assert source_id_for_report(report_status="insufficient_data", data_class=None) is None

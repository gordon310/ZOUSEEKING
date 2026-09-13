from pathlib import Path


SOURCE = (Path(__file__).parents[2] / "web" / "js" / "property-intake.js").read_text(encoding="utf-8")
RECOGNITION_SOURCE = (Path(__file__).parents[2] / "web" / "js" / "recognition.js").read_text(encoding="utf-8")
REPORT_SOURCE = (Path(__file__).parents[2] / "web" / "js" / "report-page.js").read_text(encoding="utf-8")


def test_frontend_uses_not_subdivided_option_for_cities_without_wards():
    assert "const options = wards.length ? wards : [NOT_SUBDIVIDED_VALUE];" in SOURCE
    assert 'const defaultWard = wards.length ? "" : NOT_SUBDIVIDED_VALUE;' in SOURCE
    assert "elements.ward.value = selected && options.includes(selected) ? selected : defaultWard;" in SOURCE


def test_frontend_requires_prefecture_and_city_but_not_ward():
    assert 'if (!values.prefecture) return t("intake.prefectureRequired"' in SOURCE
    assert 'if (!values.city) return t("intake.cityRequired"' in SOURCE
    assert 'values.ward' not in SOURCE[SOURCE.index("function validateLocationFields()"):SOURCE.index("async function loadLocationFields()")]


def test_frontend_module_imports_are_versioned():
    assert 'from "./api-client.js?v=' in RECOGNITION_SOURCE
    assert 'from "./api-client.js?v=' in REPORT_SOURCE
    assert 'from "./report-page-core.js?v=' in REPORT_SOURCE

from backend.app.jphouse_service import query_key


def test_query_key_normalizes_empty_and_not_subdivided_ward_values():
    expected = "东京都::涩谷区::未細分::公寓::2026::9"

    assert query_key("东京都", "涩谷区", None, "公寓", 2026, 9) == expected
    assert query_key("东京都", "涩谷区", "", "公寓", 2026, 9) == expected
    assert query_key("东京都", "涩谷区", "__not_subdivided__", "公寓", 2026, 9) == expected
    assert query_key("东京都", "涩谷区", "未细分", "公寓", 2026, 9) == expected
    assert query_key("东京都", "涩谷区", "未細分", "公寓", 2026, 9) == expected


def test_query_key_keeps_explicit_ward_distinct():
    assert query_key("大阪府", "大阪市", "北区", "公寓", 2026, 9).endswith("::北区::公寓::2026::9")

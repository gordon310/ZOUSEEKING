import json
from pathlib import Path

import pytest

from backend.app.region_names import RegionMappingReport, map_region_names, simplify_japanese


OPTIONS = json.loads(Path("web/field-options.json").read_text(encoding="utf-8"))


def test_maps_all_frontend_prefectures_from_mlit_names():
    mapped = [map_region_names(name.replace("县", "県"), "") [0] for name in OPTIONS["prefectures"]]
    assert mapped == OPTIONS["prefectures"]


def test_maps_every_niigata_city_from_japanese_and_structural_forms():
    target = "新潟县"
    county_prefixes = {
        "出雲崎町": "三島郡",
        "津南町": "中魚沼郡",
        "刈羽村": "刈羽郡",
        "聖籠町": "北蒲原郡",
        "田上町": "南蒲原郡",
        "湯泽町": "南魚沼郡",
        "关川村": "岩船郡",
        "阿贺町": "東蒲原郡",
    }
    for city in OPTIONS["cities"][target]:
        japanese = city.translate(str.maketrans({"县": "県", "东": "東", "长": "長", "冈": "岡", "泽": "沢", "关": "関", "贺": "賀", "岛": "島", "圣": "聖", "笼": "籠", "鱼": "魚", "汤": "湯", "见": "見", "叶": "葉"}))
        japanese = county_prefixes.get(city, "") + japanese
        assert map_region_names("新潟県", japanese) == (target, city, None)
    assert map_region_names("新潟県", "新潟市中央区") == (target, "新潟市", "中央区")


def test_maps_all_tokyo_and_osaka_entries_and_generic_wards():
    for prefecture, source_prefecture in (("东京都", "東京都"), ("大阪府", "大阪府")):
        for city in OPTIONS["cities"][prefecture]:
            assert map_region_names(source_prefecture, simplify_japanese(city)) == (prefecture, city, None)
    for key, ward_names in OPTIONS["wards"].items():
        prefecture, city = key.split("::")
        source_prefecture = prefecture.replace("县", "県")
        for ward in ward_names:
            assert map_region_names(source_prefecture, simplify_japanese(city) + simplify_japanese(ward)) == (
                prefecture, city, ward
            )


def test_folds_traditional_characters_on_both_sides():
    assert simplify_japanese("新潟県湯沢町關川村廣島市") == "新潟县汤泽町关川村广岛市"


@pytest.mark.parametrize(
    ("source_prefecture", "source_city", "target_prefecture", "target_city"),
    [
        ("東京都", "渋谷区", "东京都", "涩谷区"),
        ("東京都", "稲城市", "东京都", "稻城市"),
        ("東京都", "豊島区", "东京都", "丰岛区"),
        ("大阪府", "豊中市", "大阪府", "丰中市"),
        ("大阪府", "豊能郡豊能町", "大阪府", "丰能町"),
    ],
)
def test_maps_all_observed_missing_folded_municipalities(
    source_prefecture, source_city, target_prefecture, target_city
):
    options = OPTIONS
    assert target_city in options["cities"][target_prefecture]
    assert map_region_names(source_prefecture, source_city) == (target_prefecture, target_city, None)


def test_unmapped_name_is_counted_and_not_guessed():
    report = RegionMappingReport()
    assert map_region_names("新潟県", "存在しない市", report=report) == ("新潟县", None, None)
    assert report.unmapped_city == 1
    assert report.city_samples == ["存在しない市"]

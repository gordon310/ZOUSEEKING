"""Map MLIT Japanese region names to the exact frontend vocabulary."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


FIELD_OPTIONS_PATH = Path(__file__).resolve().parents[2] / "web" / "field-options.json"

PREFECTURE_NAME_MAP = {
    "北海道": "北海道", "青森県": "青森县", "岩手県": "岩手县", "宮城県": "宮城县",
    "秋田県": "秋田县", "山形県": "山形县", "福島県": "福岛县", "茨城県": "茨城县",
    "栃木県": "栃木县", "群馬県": "群馬县", "埼玉県": "埼玉县", "千葉県": "千葉县",
    "東京都": "东京都", "神奈川県": "神奈川县", "新潟県": "新潟县", "富山県": "富山县",
    "石川県": "石川县", "福井県": "福井县", "山梨県": "山梨县", "長野県": "长野县",
    "岐阜県": "岐阜县", "静岡県": "静冈县", "愛知県": "爱知县", "三重県": "三重县",
    "滋賀県": "滋贺县", "京都府": "京都府", "大阪府": "大阪府", "兵庫県": "兵庫县",
    "奈良県": "奈良县", "和歌山県": "和歌山县", "鳥取県": "鸟取县", "島根県": "岛根县",
    "岡山県": "冈山县", "広島県": "广岛县", "山口県": "山口县", "徳島県": "德岛县",
    "香川県": "香川县", "愛媛県": "爱媛县", "高知県": "高知县", "福岡県": "福冈县",
    "佐賀県": "佐贺县", "長崎県": "长崎县", "熊本県": "熊本县", "大分県": "大分县",
    "宮崎県": "宮崎县", "鹿児島県": "鹿儿岛县", "沖縄県": "冲绳县",
}

_CHAR_MAP = str.maketrans({
    "県": "县", "長": "长", "岡": "冈", "沢": "泽", "澤": "泽", "関": "关", "關": "关",
    "賀": "贺", "島": "岛", "嶋": "岛", "湯": "汤", "葉": "叶", "徳": "德", "濱": "滨",
    "濵": "滨", "廣": "广", "発": "发", "發": "发", "黒": "黑", "塩": "盐", "齋": "斋",
    "齊": "斋", "藪": "薮", "郷": "乡", "條": "条", "条": "条", "會": "会", "驒": "驒",
    "東": "东", "福": "福", "広": "广", "愛": "爱", "静": "静", "神": "神", "奈": "奈",
    "鳥": "鸟", "児": "儿", "沖": "冲", "縄": "绳", "兵": "兵", "庫": "库", "歌": "歌",
    "馬": "马", "千": "千", "宮": "宫", "戸": "户", "瀬": "濑", "檜": "桧", "調": "调",
    "貝": "贝", "門": "门", "邊": "边", "聖": "圣", "籠": "笼", "魚": "鱼", "見": "见",
})

_EXPLICIT_CITY_OVERRIDES = {
    ("東京都", "清瀬市"): "清濑市", ("東京都", "西東京市"): "西东京市", ("東京都", "檜原村"): "桧原村",
    ("大阪府", "四條畷市"): "四条畷市", ("大阪府", "河内長野市"): "河内长野市",
    ("新潟県", "阿賀野市"): "阿贺野市", ("新潟県", "阿賀町"): "阿贺町",
    ("新潟県", "湯沢町"): "湯泽町", ("新潟県", "関川村"): "关川村",
}


@dataclass
class RegionMappingReport:
    unmapped_prefecture: int = 0
    unmapped_city: int = 0
    prefecture_samples: list[str] = field(default_factory=list)
    city_samples: list[str] = field(default_factory=list)

    @staticmethod
    def _add_sample(samples: list[str], value: str) -> None:
        if value and value not in samples and len(samples) < 10:
            samples.append(value)


def load_field_options() -> dict[str, Any]:
    return json.loads(FIELD_OPTIONS_PATH.read_text(encoding="utf-8"))


def simplify_japanese(value: str) -> str:
    return value.translate(_CHAR_MAP)


def _target_prefecture(source: str, options: dict[str, Any]) -> str | None:
    direct = PREFECTURE_NAME_MAP.get(source)
    if direct in options["prefectures"]:
        return direct
    folded = simplify_japanese(source)
    return next((item for item in options["prefectures"] if simplify_japanese(item) == folded), None)


def _target_city(source_prefecture: str, target_prefecture: str, municipality: str, options: dict[str, Any]) -> tuple[str | None, str | None]:
    cities = options["cities"].get(target_prefecture, [])
    candidates = [(city, simplify_japanese(city)) for city in cities]
    explicit = _EXPLICIT_CITY_OVERRIDES.get((source_prefecture, municipality))
    if explicit in cities:
        return explicit, None

    def exact(value: str) -> str | None:
        folded = simplify_japanese(value)
        return next((city for city, candidate in candidates if candidate == folded), None)

    city = exact(municipality)
    if city:
        return city, None

    without_county = re.sub(r"^.+郡", "", municipality, count=1)
    if without_county != municipality:
        city = exact(without_county)
        if city:
            return city, None

    for city, folded_city in sorted(candidates, key=lambda pair: len(pair[1]), reverse=True):
        if not simplify_japanese(municipality).startswith(folded_city):
            continue
        remainder = simplify_japanese(municipality)[len(folded_city):]
        ward_names = options.get("wards", {}).get(f"{target_prefecture}::{city}", [])
        ward = next((item for item in ward_names if simplify_japanese(item) == remainder), None)
        if ward:
            return city, ward
    return None, None


def map_region_names(
    source_prefecture: str, source_municipality: str, *, report: RegionMappingReport | None = None
) -> tuple[str | None, str | None, str | None]:
    source_prefecture = source_prefecture.strip()
    source_municipality = source_municipality.strip()
    options = load_field_options()
    target_prefecture = _target_prefecture(source_prefecture, options)
    if target_prefecture is None:
        if report:
            report.unmapped_prefecture += 1
            report._add_sample(report.prefecture_samples, source_prefecture)
        return None, None, None
    target_city, target_ward = _target_city(source_prefecture, target_prefecture, source_municipality, options)
    if target_city is None:
        if report:
            report.unmapped_city += 1
            report._add_sample(report.city_samples, source_municipality)
        return target_prefecture, None, None
    if target_city not in options["cities"].get(target_prefecture, []):
        return target_prefecture, None, None
    if target_ward is not None and target_ward not in options.get("wards", {}).get(f"{target_prefecture}::{target_city}", []):
        if report:
            report.unmapped_city += 1
            report._add_sample(report.city_samples, source_municipality)
        return target_prefecture, target_city, None
    return target_prefecture, target_city, target_ward

"""JIS municipality lookup and conversion to the query form's Chinese values."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_CODES_PATH = Path(__file__).resolve().parents[3] / "data" / "municipality_codes.json"
_JAPANESE_TO_QUERY = str.maketrans({
    "亀": "龟", "亘": "亘", "丼": "丼", "亞": "亚", "仮": "假", "佛": "佛",
    "侭": "尽", "倶": "俱", "偽": "伪", "傘": "伞", "僅": "仅", "儘": "尽",
    "兒": "儿", "冊": "册", "冨": "富", "凛": "凛", "刈": "刈", "剝": "剥",
    "劍": "剑", "勞": "劳", "匝": "匝", "區": "区", "卽": "即", "卷": "卷",
    "參": "参", "叡": "睿", "吳": "吴", "啓": "启", "國": "国", "圓": "圆",
    "圴": "均", "塚": "冢", "壓": "压", "壹": "壹", "奧": "奥", "姬": "姬",
    "學": "学", "實": "实", "寶": "宝", "宮": "宫", "對": "对", "專": "专",
    "將": "将", "尞": "寮", "屆": "届", "峯": "峰", "島": "岛", "崗": "岗",
    "嶋": "岛", "巖": "岩", "廣": "广", "廳": "厅", "彌": "弥", "從": "从",
    "德": "德", "惠": "惠", "愛": "爱", "懷": "怀", "戶": "户", "擇": "择",
    "數": "数", "斉": "齐", "斷": "断", "旣": "既", "晝": "昼", "會": "会",
    "曾": "曾", "朔": "朔", "來": "来", "東": "东", "桧": "桧", "樂": "乐",
    "榮": "荣", "櫻": "樱", "權": "权", "歡": "欢", "氣": "气", "澤": "泽",
    "浜": "滨", "濱": "滨", "瀨": "濑", "燒": "烧", "爲": "为", "狹": "狭", "獨": "独",
    "瓊": "琼", "產": "产", "當": "当", "發": "发", "眞": "真", "礒": "矶",
    "祕": "秘", "禮": "礼", "稻": "稻", "穗": "穗", "窪": "洼", "篠": "筱",
    "簾": "帘", "粹": "粹", "經": "经", "緣": "缘", "總": "总", "綱": "纲",
    "渋": "涩", "緑": "绿", "繩": "绳", "纈": "缬", "罐": "罐", "聖": "圣", "脫": "脱",
    "舊": "旧", "莊": "庄", "華": "华", "萬": "万", "薗": "园", "藏": "藏",
    "螢": "萤", "表": "表", "襌": "禅", "覺": "觉", "覽": "览", "觸": "触",
    "譽": "誉", "證": "证", "譯": "译", "讀": "读", "豐": "丰", "貴": "贵",
    "賣": "卖", "賴": "赖", "贊": "赞", "越": "越", "跡": "迹", "踊": "踊",
    "轉": "转", "邊": "边", "鄕": "乡", "鄰": "邻", "釋": "释", "鐵": "铁",
    "鑛": "矿", "長": "长", "門": "门", "關": "关", "陸": "陆", "險": "险",
    "雜": "杂", "靜": "静", "響": "响", "顯": "显", "驛": "驿", "髙": "高",
    "豊": "丰", "館": "馆", "帯": "带", "見": "见", "沢": "泽", "鶴": "鹤", "鷹": "鹰", "鹿": "鹿", "龍": "龙", "龜": "龟",
})

_PREFECTURE_QUERY_NAMES = {
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


def _query_name(value: str) -> str:
    return value.translate(_JAPANESE_TO_QUERY)


def load_municipality_codes(path: Path = _CODES_PATH) -> dict[str, dict[str, str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def lookup_municipality(code: str, *, codes: dict[str, dict[str, str]] | None = None) -> dict[str, str] | None:
    record = (codes if codes is not None else load_municipality_codes()).get(str(code).strip())
    if not isinstance(record, dict):
        return None
    raw_prefecture = str(record.get("prefecture", ""))
    prefecture = _PREFECTURE_QUERY_NAMES.get(raw_prefecture, _query_name(raw_prefecture))
    municipality = _query_name(str(record.get("city", "")))
    if not prefecture or not municipality:
        return None
    match = re.fullmatch(r"(.+市)(.+区)", municipality)
    if match:
        return {"prefecture": prefecture, "city": match.group(1), "ward": match.group(2)}
    return {"prefecture": prefecture, "city": municipality, "ward": ""}

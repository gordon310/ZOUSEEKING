import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Ward:
    name_ja: str
    name_zh: str
    suumo_code: str
    bw_slug: str
    intro: str
    tower_hint: str


WARDS = [
    Ward("千代田区", "千代田区", "chiyoda", "13101", "皇居、大手町、丸之内、秋叶原这一圈。", "番町、麹町、饭田桥一带高端公寓不少。"),
    Ward("中央区", "中央区", "chuo", "13102", "银座、日本桥、月岛、胜哄、晴海这一圈。", "月岛、胜哄、晴海这一带塔楼尤其多。"),
    Ward("港区", "港区", "minato", "13103", "麻布、赤坂、六本木、青山、芝浦台场这一圈。", "湾岸、麻布、赤坂一带塔楼和高端公寓都很多。"),
    Ward("新宿区", "新宿区", "shinjuku", "13104", "新宿、四谷、神乐坂、高田马场这一圈。", "西新宿高层公寓存在感很强。"),
    Ward("文京区", "文京区", "bunkyo", "13105", "本乡、后乐园、茗荷谷、千石这一圈。", "整体更偏文教住宅区，塔楼数量没湾岸多。"),
    Ward("台東区", "台东区", "taito", "13106", "上野、浅草、御徒町、蔵前这一圈。", "浅草、上野周边中高层公寓不少。"),
    Ward("墨田区", "墨田区", "sumida", "13107", "锦糸町、押上、两国、曳舟这一圈。", "押上、锦糸町一带高层公寓比较有存在感。"),
    Ward("江東区", "江东区", "koto", "13108", "丰洲、东阳町、门前仲町、有明这一圈。", "丰洲、有明、东云是东京湾岸塔楼重镇。"),
    Ward("品川区", "品川区", "shinagawa", "13109", "大崎、五反田、天王洲、武藏小山这一圈。", "大崎、天王洲、武藏小山都有塔楼代表。"),
    Ward("目黒区", "目黑区", "meguro", "13110", "中目黑、目黑、自由之丘、祐天寺这一圈。", "整体更偏低密住宅，高层塔楼没湾岸那么密。"),
    Ward("大田区", "大田区", "ota", "13111", "蒲田、大森、田园调布、羽田这一圈。", "蒲田、大森周边中高层公寓更多。"),
    Ward("世田谷区", "世田谷区", "setagaya", "13112", "三轩茶屋、下北泽、二子玉川、成城这一圈。", "二子玉川周边高层公寓比较有代表性。"),
    Ward("渋谷区", "涩谷区", "shibuya", "13113", "涩谷、惠比寿、代官山、代代木这一圈。", "涩谷、惠比寿一带高端公寓不少。"),
    Ward("中野区", "中野区", "nakano", "13114", "中野、东中野、新井药师、野方这一圈。", "中野站周边再开发后高层感增强。"),
    Ward("杉並区", "杉并区", "suginami", "13115", "荻洼、高圆寺、阿佐谷、永福町这一圈。", "整体住宅氛围强，塔楼不是主角。"),
    Ward("豊島区", "丰岛区", "toshima", "13116", "池袋、目白、巢鸭、大塚这一圈。", "池袋周边高层公寓较集中。"),
    Ward("北区", "北区", "kita", "13117", "赤羽、王子、田端这一圈。", "赤羽、王子站周边中高层公寓较多。"),
    Ward("荒川区", "荒川区", "arakawa", "13118", "日暮里、町屋、南千住这一圈。", "南千住、日暮里周边塔楼和大规模公寓较多。"),
    Ward("板橋区", "板桥区", "itabashi", "13119", "板桥、大山、成增、高岛平这一圈。", "板桥站、大山周边有中高层公寓。"),
    Ward("練馬区", "练马区", "nerima", "13120", "练马、石神井公园、光丘、大泉学园这一圈。", "光丘、大泉一带大规模住宅较多。"),
    Ward("足立区", "足立区", "adachi", "13121", "北千住、绫濑、西新井这一圈。", "北千住、西新井周边高层公寓更常见。"),
    Ward("葛飾区", "葛饰区", "katsushika", "13122", "龟有、新小岩、金町、柴又这一圈。", "金町、新小岩周边再开发公寓值得看。"),
    Ward("江戸川区", "江户川区", "edogawa", "13123", "小岩、葛西、西葛西、船堀这一圈。", "葛西、西葛西、小岩周边公寓供应较多。"),
]


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 jphouse research"})
    with urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="ignore")


def parse_suumo_rents(html: str):
    result = {}
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    for layout in ["1LDK", "2LDK", "3LDK"]:
        match = re.search(rf"{layout}\s*([0-9.]+|-+)\s*(?:万円)?", text)
        if match:
            result[layout] = None if match.group(1).startswith("-") else float(match.group(1))
    updated = re.search(r"([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日更新)", text)
    return result, updated.group(1) if updated else ""


def yen_text_to_man_yen(text: str):
    oku = 0
    man = 0
    match_oku = re.search(r"([0-9]+)億", text)
    match_man = re.search(r"([0-9]+)万", text)
    if match_oku:
        oku = int(match_oku.group(1)) * 10000
    if match_man:
        man = int(match_man.group(1))
    if not match_oku and not match_man:
        digits = re.sub(r"[^0-9]", "", text)
        return round(int(digits) / 10000) if digits else None
    return oku + man


def parse_tochidai(html: str, ward_name: str):
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    unit = re.search(r"最新のマンション売却価格は、平米単価\s*([0-9]+)万([0-9]+)\s*円", text)
    updated = re.search(r"(2026年［令和8年］1～3月)", text)
    layouts = {}
    for layout in ["1LDK", "2LDK", "3LDK"]:
        match = re.search(rf"{layout}の平均価格は\s*([^。]+?)\s*円です", text)
        if not match:
            match = re.search(rf"2026年［令和8年］\s*中古マンション等\s*{layout}\s*([^+\\-]+?)\s*円", text)
        if match:
            layouts[layout] = yen_text_to_man_yen(match.group(1))
    if not all(layouts.get(layout) for layout in ["1LDK", "2LDK", "3LDK"]):
        raise RuntimeError(f"{ward_name} Tochidai sale parse failed: {layouts}")
    return {
        "layout_price_man_yen": layouts,
        "unit_man_yen_per_sqm": (int(unit.group(1)) + int(unit.group(2)) / 10000) if unit else None,
        "updated": updated.group(1) if updated else "",
    }


def jpy_man_to_rmb_man(man_yen, rate=4.23):
    # 1万日元 = 423 RMB = 0.0423万 RMB
    return man_yen * rate / 100


def rent_row(layout, area, rent_man_yen):
    if rent_man_yen is None:
        return {
            "layout": layout,
            "area": f"约{round(area - 3)}–{round(area + 3)}㎡",
            "amount_jpy": "暂无样本",
            "amount_rmb": "",
            "unit_jpy": "暂无样本",
            "unit_rmb": "",
        }
    unit_yen = round(rent_man_yen * 10000 / area)
    return {
        "layout": layout,
        "area": f"约{round(area - 3)}–{round(area + 3)}㎡",
        "amount_jpy": f"{rent_man_yen:.1f}万日元/月",
        "amount_rmb": f"≈{jpy_man_to_rmb_man(rent_man_yen):.2f}万RMB/月",
        "unit_jpy": f"约{unit_yen:,}日元/㎡/月",
        "unit_rmb": f"≈{round(unit_yen * 0.0423):,}RMB/㎡/月",
    }


def sale_rows_from_tochidai(sale):
    unit = sale.get("unit_man_yen_per_sqm") or 150
    assumptions = [("1LDK", 42), ("2LDK", 62), ("3LDK", 82)]
    rows = []
    for layout, area in assumptions:
        price = sale["layout_price_man_yen"][layout]
        rows.append(
            {
                "layout": layout,
                "area": f"约{round(area - 3)}–{round(area + 3)}㎡",
                "amount_jpy": f"约{price:,}万日元",
                "amount_rmb": f"≈{round(jpy_man_to_rmb_man(price)):,}万RMB",
                "unit_jpy": f"约{unit:g}万日元/㎡",
                "unit_rmb": f"≈{unit * 0.0423:.1f}万RMB/㎡",
            }
        )
    return rows


def make_config(ward, rents, suumo_updated, sale, publish_month):
    rent_areas = {"1LDK": 42, "2LDK": 62, "3LDK": 82}
    rental_rows = [rent_row(layout, rent_areas[layout], rents[layout]) for layout in ["1LDK", "2LDK", "3LDK"]]
    sale_rows = sale_rows_from_tochidai(sale)
    ratios = []
    for rent, sale_row in zip(rental_rows, sale_rows):
        if rent["amount_jpy"] == "暂无样本":
            ratios.append((rent["layout"], None))
            continue
        rent_man = float(rent["amount_jpy"].split("万")[0])
        price_man = int(re.sub(r"[^0-9]", "", sale_row["amount_jpy"]))
        ratios.append((rent["layout"], rent_man * 12 / price_man * 100))
    ratio_line = "｜".join(
        f"{layout}｜{'暂无租金样本' if ratio is None else f'约{ratio:.2f}%'}" for layout, ratio in ratios
    )
    slug = f"jphouse_tokyo_23ku_{ward.suumo_code}_2026_08"
    return {
        "template_name": "jphouse",
        "slug": slug,
        "title": f"东京{ward.name_zh}塔楼，租还是买？",
        "publish_month": publish_month,
        "cover": {
            "line1": f"东京{ward.name_zh}",
            "line2": "塔楼租还是买？",
            "tagline": "我替钱包瞄了一眼",
            "note": "吃饱饭，没事干，纯分享。",
        },
        "intro": [
            f"东京{ward.name_zh}，大概就是{ward.intro}",
            f"{ward.tower_hint}价格嘛，也很懂怎么让钱包保持清醒。",
        ],
        "explain": [
            "小白翻译一下：",
            "LDK=客厅+餐厅+厨房，前面的数字=卧室数量。",
            "1LDK差不多一房一厅，2LDK两房一厅，3LDK三房一厅。",
            "塔楼一般指高层/超高层公寓，这里按公开相场做一个粗略快照。",
        ],
        "exchange_rate_note": "汇率按发布当天约算：100日元≈4.23RMB。",
        "sections": {
            "rental": {
                "title": "租房子",
                "subtitle": f"{ward.name_zh}公开相场快照 · {publish_month}",
                "note": "汇率约算：100日元≈4.23RMB。钱包自动进入省电模式。",
                "rows": rental_rows,
            },
            "sale": {
                "title": "买房子",
                "subtitle": f"中古マンション成交均价参考 · {publish_month}",
                "note": "成交均价来自国交省取引数据整理。钱包先别急着报警。",
                "rows": sale_rows,
            },
        },
        "summary": {
            "title": "总而言之",
            "line": ratio_line,
            "note": "算法：月租×12÷买房成交均价，钱包看完继续沉默。",
        },
        "closing": "数据如有不对，欢迎评论区狠狠地喷，我先把头低下。",
        "hashtags": ["东京房产", f"{ward.name_zh}房产", "东京塔楼", "日本租房", "日本买房"],
        "data_sources": [
            {
                "name": f"SUUMO {ward.name_ja}租赁相场",
                "url": f"https://suumo.jp/chintai/soba/tokyo/sc_{ward.suumo_code}/?ts=1",
                "usage": f"1LDK/2LDK/3LDK租金相场（{suumo_updated or '页面更新日未读取'}；空值保留为暂无样本）",
            },
            {
                "name": f"Tochidai {ward.name_ja}中古マンション成交相场",
                "url": f"https://tochidai.info/mansion/tokyo/{ward.suumo_code}/",
                "usage": f"1LDK/2LDK/3LDK成交均价、平米单价（{sale.get('updated') or '更新日未读取'}）",
            },
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish-month", default="2026年8月")
    parser.add_argument("--limit", type=int, default=23)
    args = parser.parse_args()

    collected = []
    config_dir = ROOT / "configs" / "jphouse_23ku"
    config_dir.mkdir(parents=True, exist_ok=True)
    for ward in WARDS[: args.limit]:
        suumo_url = f"https://suumo.jp/chintai/soba/tokyo/sc_{ward.suumo_code}/?ts=1"
        tochidai_url = f"https://tochidai.info/mansion/tokyo/{ward.suumo_code}/"
        rents, suumo_updated = parse_suumo_rents(fetch_text(suumo_url))
        sale = parse_tochidai(fetch_text(tochidai_url), ward.name_ja)
        if not all(layout in rents for layout in ["1LDK", "2LDK", "3LDK"]):
            raise RuntimeError(f"{ward.name_ja} SUUMO rent parse failed: {rents}")
        config = make_config(ward, rents, suumo_updated, sale, args.publish_month)
        path = config_dir / f"{ward.suumo_code}.json"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        collected.append({"ward": ward.name_ja, "config": str(path), "rents": rents, "suumo_updated": suumo_updated, "sale": sale})

    out = ROOT / "data" / "collected" / "jphouse_23ku_sources.json"
    out.write_text(json.dumps(collected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(collected), "output": str(out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

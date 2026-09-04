import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from build_jphouse_23ku import fetch_text, jpy_man_to_rmb_man, parse_suumo_rents, parse_tochidai, rent_row
from generate_xhs_package import generate


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class OsakaWard:
    name_ja: str
    name_zh: str
    slug: str
    suumo_code: str
    tochidai_slug: str
    intro: str
    tower_hint: str


WARDS = [
    OsakaWard("北区", "北区", "kita", "osakashikita", "osaka-kita", "梅田、中津、中崎町、天满这一圈。", "梅田周边商务和生活机能都很强，高层公寓存在感很高。"),
    OsakaWard("都島区", "都岛区", "miyakojima", "osakashimiyakojima", "osaka-miyakojima", "京桥、都岛、樱之宫这一圈。", "京桥和樱之宫周边中高层公寓不少。"),
    OsakaWard("福島区", "福岛区", "fukushima", "osakashifukushima", "osaka-fukushima", "福岛、野田、新福岛这一圈。", "离梅田近，住宅塔楼和高层公寓都比较有存在感。"),
    OsakaWard("此花区", "此花区", "konohana", "osakashikonohana", "osaka-konohana", "西九条、千鸟桥、USJ周边这一圈。", "临湾和再开发区域有一定高层住宅存在。"),
    OsakaWard("西区", "西区", "nishi", "osakashinishi", "osaka-nishi", "堀江、本町、阿波座、九条这一圈。", "市中心生活感强，高层公寓和投资型公寓都不少。"),
    OsakaWard("港区", "港区", "minato", "osakashiminato", "osaka-minato", "弁天町、大阪港、朝潮桥这一圈。", "弁天町一带高层住宅比较有代表性。"),
    OsakaWard("大正区", "大正区", "taisho", "osakashitaisho", "osaka-taisho", "大正、泉尾、平尾这一圈。", "整体更生活区，高层塔楼不是最密集的主角。"),
    OsakaWard("天王寺区", "天王寺区", "tennoji", "osakashitennoji", "osaka-tennoji", "天王寺、上本町、四天王寺这一圈。", "交通和教育资源强，高层公寓关注度不低。"),
    OsakaWard("浪速区", "浪速区", "naniwa", "osakashinaniwa", "osaka-naniwa", "难波、大国町、樱川、日本桥这一圈。", "市中心感强，高层公寓和投资型公寓都比较常见。"),
    OsakaWard("西淀川区", "西淀川区", "nishiyodogawa", "osakashinishiyodogawa", "osaka-nishiyodogawa", "御币岛、姬岛、千船这一圈。", "整体偏生活住宅区，中高层公寓更多见。"),
    OsakaWard("淀川区", "淀川区", "yodogawa", "osakashiyodogawa", "osaka-yodogawa", "新大阪、十三、东三国这一圈。", "新大阪和十三周边交通强，高层公寓需求比较稳定。"),
    OsakaWard("东淀川区", "东淀川区", "higashiyodogawa", "osakashihigashiyodogawa", "osaka-higashiyodogawa", "淡路、上新庄、瑞光这一圈。", "住宅氛围更明显，高层塔楼密度不算特别夸张。"),
    OsakaWard("东成区", "东成区", "higashinari", "osakashihigashinari", "osaka-higashinari", "森之宫、绿桥、今里这一圈。", "靠近大阪城东侧，中高层公寓比较常见。"),
    OsakaWard("生野区", "生野区", "ikuno", "osakashiino", "osaka-ikuno", "鹤桥、今里、北巽这一圈。", "生活区属性强，塔楼不是最主流，但公寓供应不少。"),
    OsakaWard("旭区", "旭区", "asahi", "osakashiasahi", "osaka-asahi", "千林、大宫、关目高殿这一圈。", "整体偏生活住宅区，高层公寓数量相对克制。"),
    OsakaWard("城東区", "城东区", "joto", "osakashijoto", "osaka-joto", "蒲生四丁目、京桥东侧、关目这一圈。", "交通和生活便利，中高层公寓存在感不错。"),
    OsakaWard("鶴見区", "鹤见区", "tsurumi", "osakashitsurumi", "osaka-tsurumi", "横堤、放出、鹤见绿地这一圈。", "住宅区气质更强，大规模公寓比纯塔楼更常见。"),
    OsakaWard("阿倍野区", "阿倍野区", "abeno", "osakashiabeno", "osaka-abeno", "天王寺南侧、阿倍野、昭和町这一圈。", "天王寺周边高层住宅和高端公寓关注度很高。"),
    OsakaWard("住之江区", "住之江区", "suminoe", "osakashisuminoe", "osaka-suminoe", "住之江公园、北加贺屋、南港这一圈。", "南港一带有临湾高层住宅代表。"),
    OsakaWard("住吉区", "住吉区", "sumiyoshi", "osakashisumiyoshi", "osaka-sumiyoshi", "长居、我孙子、住吉大社这一圈。", "整体偏生活住宅区，中高层公寓比较常见。"),
    OsakaWard("东住吉区", "东住吉区", "higashisumiyoshi", "osakashihigashisumiyoshi", "osaka-higashisumiyoshi", "田边、驹川中野、长居东侧这一圈。", "生活区属性明显，塔楼不是主角。"),
    OsakaWard("平野区", "平野区", "hirano", "osakashihirano", "osaka-hirano", "平野、喜连瓜破、加美这一圈。", "住宅供应比较多，高层塔楼密度不算高。"),
    OsakaWard("西成区", "西成区", "nishinari", "osakashinishinari", "osaka-nishinari", "天下茶屋、岸里、花园町这一圈。", "交通方便，公寓需求有，但塔楼属性相对没市中心强。"),
]


def yen_text_to_int_man(text: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else None


def sale_rows_from_tochidai(sale):
    unit = sale.get("unit_man_yen_per_sqm") or 0
    assumptions = [("1LDK", 42), ("2LDK", 62), ("3LDK", 82)]
    rows = []
    for layout, area in assumptions:
        price = sale["layout_price_man_yen"].get(layout)
        if not price:
            rows.append(
                {
                    "layout": layout,
                    "area": f"约{round(area - 3)}–{round(area + 3)}㎡",
                    "amount_jpy": "暂无样本",
                    "amount_rmb": "",
                    "unit_jpy": "暂无样本",
                    "unit_rmb": "",
                }
            )
            continue
        rows.append(
            {
                "layout": layout,
                "area": f"约{round(area - 3)}–{round(area + 3)}㎡",
                "amount_jpy": f"约{price:,}万日元",
                "amount_rmb": f"≈{round(jpy_man_to_rmb_man(price)):,}万RMB",
                "unit_jpy": f"约{unit:g}万日元/㎡" if unit else "暂无样本",
                "unit_rmb": f"≈{unit * 0.0423:.1f}万RMB/㎡" if unit else "",
            }
        )
    return rows


def ratio_line(rental_rows, sale_rows):
    ratios = []
    for rent, sale in zip(rental_rows, sale_rows):
        if rent["amount_jpy"] == "暂无样本" or sale["amount_jpy"] == "暂无样本":
            ratios.append(f"{rent['layout']}｜暂无样本")
            continue
        rent_man = float(rent["amount_jpy"].split("万")[0])
        price_man = yen_text_to_int_man(sale["amount_jpy"])
        ratios.append(f"{rent['layout']}｜约{rent_man * 12 / price_man * 100:.2f}%")
    return "｜".join(ratios)


def make_config(ward: OsakaWard, rents, suumo_updated, sale, publish_month):
    rent_areas = {"1LDK": 42, "2LDK": 62, "3LDK": 82}
    rental_rows = [rent_row(layout, rent_areas[layout], rents.get(layout)) for layout in ["1LDK", "2LDK", "3LDK"]]
    sale_rows = sale_rows_from_tochidai(sale)
    return {
        "template_name": "jphouse",
        "slug": f"jphouse_osaka_{ward.slug}_tower_2026_08",
        "title": f"大阪{ward.name_zh}塔楼，租还是买？",
        "publish_month": publish_month,
        "generated_at": "2026-08-23",
        "status": "generated",
        "cover": {
            "line1": f"大阪{ward.name_zh}",
            "line2": "塔楼租还是买？",
            "tagline": "我替钱包瞄了一眼",
            "note": "公开相场数据快照",
        },
        "intro": [
            f"大阪{ward.name_zh}，大概就是{ward.intro}",
            f"{ward.tower_hint}这里按公开相场做一份数据快照。",
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
                "subtitle": f"大阪{ward.name_zh}公开相场快照 · {publish_month}",
                "note": "汇率约算：100日元≈4.23RMB。",
                "rows": rental_rows,
            },
            "sale": {
                "title": "买房子",
                "subtitle": f"中古マンション成交均价参考 · {publish_month}",
                "note": "成交均价来自国交省取引数据整理。",
                "rows": sale_rows,
            },
        },
        "summary": {
            "title": "总而言之",
            "line": ratio_line(rental_rows, sale_rows),
            "note": "算法：月租×12÷买房成交均价，只看公开相场，不替钱包做主。",
        },
        "hashtags": [],
        "data_sources": [
            {
                "name": f"SUUMO 大阪市{ward.name_ja}租赁相场",
                "url": f"https://suumo.jp/chintai/soba/osaka/sc_{ward.suumo_code}/?ts=1",
                "usage": f"1LDK/2LDK/3LDK租金相场（{suumo_updated or '页面更新日未读取'}；空值保留为暂无样本）",
            },
            {
                "name": f"Tochidai 大阪市{ward.name_ja}中古マンション成交相场",
                "url": f"https://tochidai.info/mansion/osaka/{ward.tochidai_slug}/",
                "usage": f"1LDK/2LDK/3LDK成交均价、平米单价（{sale.get('updated') or '更新日未读取'}）",
            },
            {
                "name": "JPY/CNY 汇率参考",
                "url": "https://www.fx-rate.net/JPY/CNY/",
                "usage": "发布日附近汇率约算：100日元≈4.23RMB",
            },
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Build jphouse data packages for Osaka city wards, excluding Chuo ward.")
    parser.add_argument("--publish-month", default="2026年8月")
    parser.add_argument("--limit", type=int, default=len(WARDS))
    args = parser.parse_args()

    config_dir = ROOT / "configs" / "jphouse_osaka_wards"
    output_root = ROOT / "data" / "output" / "jphouse_osaka_wards"
    config_dir.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    collected = []
    failed = []
    for ward in WARDS[: args.limit]:
        try:
            suumo_url = f"https://suumo.jp/chintai/soba/osaka/sc_{ward.suumo_code}/?ts=1"
            tochidai_url = f"https://tochidai.info/mansion/osaka/{ward.tochidai_slug}/"
            rents, suumo_updated = parse_suumo_rents(fetch_text(suumo_url))
            sale = parse_tochidai(fetch_text(tochidai_url), ward.name_ja)
            config = make_config(ward, rents, suumo_updated, sale, args.publish_month)
            config_path = config_dir / f"{ward.slug}.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            output_dir = output_root / config["slug"]
            generate(config_path, output_dir)
            collected.append(
                {
                    "ward": ward.name_ja,
                    "config": str(config_path),
                    "output": str(output_dir),
                    "rents": rents,
                    "suumo_updated": suumo_updated,
                    "sale": sale,
                }
            )
            print(f"generated {ward.name_ja}: {config['slug']}")
        except Exception as exc:
            failed.append({"ward": ward.name_ja, "error": str(exc)})
            print(f"failed {ward.name_ja}: {exc}")

    summary = {"count": len(collected), "failed_count": len(failed), "collected": collected, "failed": failed}
    out = ROOT / "data" / "collected" / "jphouse_osaka_wards_sources.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    index = output_root / "index.md"
    index.write_text(
        "# jphouse 大阪市内各区塔楼数据｜2026年8月\n\n"
        + "\n".join(f"- {item['ward']}：{item['output']}/data_detail.md" for item in collected)
        + ("\n\n## 未生成\n" + "\n".join(f"- {item['ward']}：{item['error']}" for item in failed) if failed else "")
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"generated": len(collected), "failed": len(failed), "summary": str(out), "index": str(index)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

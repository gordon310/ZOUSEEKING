import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from build_jphouse_23ku import fetch_text, jpy_man_to_rmb_man, parse_suumo_rents, parse_tochidai, rent_row
from generate_xhs_package import generate


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class YokohamaWard:
    name_ja: str
    name_zh: str
    slug: str
    suumo_code: str
    tochidai_slug: str
    intro: str
    tower_hint: str


WARDS = [
    YokohamaWard("鶴見区", "鹤见区", "tsurumi", "yokohamashitsurumi", "yokohama-tsurumi", "鹤见、京急鹤见、矢向这一圈。", "靠近东京和川崎，通勤型公寓需求比较稳定。"),
    YokohamaWard("神奈川区", "神奈川区", "kanagawa", "yokohamashikanagawa", "yokohama-kanagawa", "东神奈川、反町、白乐这一圈。", "靠近横滨站北侧，高层公寓和交通便利型住宅都有存在感。"),
    YokohamaWard("西区", "西区", "nishi", "yokohamashinishi", "yokohama-nishi", "横滨站、みなとみらい、高岛町这一圈。", "横滨塔楼主战场之一，钱包容易被海风吹清醒。"),
    YokohamaWard("中区", "中区", "naka", "yokohamashinaka", "yokohama-naka", "关内、樱木町、元町中华街、山下公园这一圈。", "港未来周边和关内一带，高层住宅关注度很高。"),
    YokohamaWard("南区", "南区", "minami", "yokohamashiminami", "yokohama-minami", "弘明寺、井土ヶ谷、吉野町这一圈。", "生活区属性强，中高层公寓比纯塔楼更常见。"),
    YokohamaWard("港南区", "港南区", "konan", "yokohamashikonan", "yokohama-konan", "上大冈、港南台、上永谷这一圈。", "上大冈周边交通强，高层住宅有代表性。"),
    YokohamaWard("保土ケ谷区", "保土谷区", "hodogaya", "yokohamashihodogaya", "yokohama-hodogaya", "保土ケ谷、星川、天王町这一圈。", "通勤住宅区气质明显，中高层公寓比较常见。"),
    YokohamaWard("旭区", "旭区", "asahi", "yokohamashiasahi", "yokohama-asahi", "二俣川、鹤峰、希望丘这一圈。", "二俣川再开发后，高层住宅关注度更高。"),
    YokohamaWard("磯子区", "矶子区", "isogo", "yokohamashiisogo", "yokohama-isogo", "矶子、新杉田、洋光台这一圈。", "临海和丘陵住宅混在一起，大规模公寓不少。"),
    YokohamaWard("金沢区", "金泽区", "kanazawa", "yokohamashikanazawa", "yokohama-kanazawa", "金泽文库、金泽八景、能见台这一圈。", "生活和海边感都比较强，塔楼密度不算特别夸张。"),
    YokohamaWard("港北区", "港北区", "kohoku", "yokohamashikohoku", "yokohama-kohoku", "新横滨、日吉、菊名、大仓山这一圈。", "新横滨和日吉周边交通强，高层公寓需求稳。"),
    YokohamaWard("緑区", "绿区", "midori", "yokohamashimidori", "yokohama-midori", "中山、十日市场、长津田这一圈。", "住宅区气质更强，大规模公寓比塔楼更常见。"),
    YokohamaWard("青葉区", "青叶区", "aoba", "yokohamashiaoba", "yokohama-aoba", "青叶台、たまプラーザ、市が尾这一圈。", "田园都市线沿线人气高，品质型公寓关注度不错。"),
    YokohamaWard("都筑区", "都筑区", "tsuzuki", "yokohamashitsuzuki", "yokohama-tsuzuki", "センター北、センター南、仲町台这一圈。", "港北ニュータウン一带，大规模公寓和家庭向住宅多。"),
    YokohamaWard("戸塚区", "户塚区", "totsuka", "yokohamashitotsuka", "yokohama-totsuka", "户塚、东户塚、舞冈这一圈。", "东户塚和户塚站周边高层住宅比较有代表性。"),
    YokohamaWard("栄区", "荣区", "sakae", "yokohamashisakae", "yokohama-sakae", "本乡台、大船北侧这一圈。", "整体偏安静住宅区，塔楼不是最主流。"),
    YokohamaWard("泉区", "泉区", "izumi", "yokohamashiizumi", "yokohama-izumi", "立场、泉中央、弥生台这一圈。", "生活住宅区属性强，中高层公寓为主。"),
    YokohamaWard("瀬谷区", "濑谷区", "seya", "yokohamashiseya", "yokohama-seya", "濑谷、三ツ境这一圈。", "住宅区气质更明显，塔楼密度相对低。"),
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


def make_config(ward: YokohamaWard, rents, suumo_updated, sale, publish_month):
    rent_areas = {"1LDK": 42, "2LDK": 62, "3LDK": 82}
    rental_rows = [rent_row(layout, rent_areas[layout], rents.get(layout)) for layout in ["1LDK", "2LDK", "3LDK"]]
    sale_rows = sale_rows_from_tochidai(sale)
    return {
        "template_name": "jphouse",
        "slug": f"jphouse_yokohama_{ward.slug}_tower_2026_08",
        "title": f"横滨{ward.name_zh}塔楼，租还是买？",
        "publish_month": publish_month,
        "generated_at": "2026-08-23",
        "status": "generated",
        "cover": {
            "line1": f"横滨{ward.name_zh}",
            "line2": "塔楼租还是买？",
            "tagline": "我替钱包瞄了一眼",
            "note": "公开相场数据快照",
        },
        "intro": [
            f"横滨{ward.name_zh}，大概就是{ward.intro}",
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
                "subtitle": f"横滨{ward.name_zh}公开相场快照 · {publish_month}",
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
                "name": f"SUUMO 横浜市{ward.name_ja}租赁相场",
                "url": f"https://suumo.jp/chintai/soba/kanagawa/sc_{ward.suumo_code}/?ts=1",
                "usage": f"1LDK/2LDK/3LDK租金相场（{suumo_updated or '页面更新日未读取'}；空值保留为暂无样本）",
            },
            {
                "name": f"Tochidai 横浜市{ward.name_ja}中古マンション成交相场",
                "url": f"https://tochidai.info/mansion/kanagawa/{ward.tochidai_slug}/",
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
    parser = argparse.ArgumentParser(description="Build jphouse data packages for Yokohama city wards.")
    parser.add_argument("--publish-month", default="2026年8月")
    parser.add_argument("--limit", type=int, default=len(WARDS))
    args = parser.parse_args()

    config_dir = ROOT / "configs" / "jphouse_yokohama_wards"
    output_root = ROOT / "data" / "output" / "jphouse_yokohama_wards"
    config_dir.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    collected = []
    failed = []
    for ward in WARDS[: args.limit]:
        try:
            suumo_url = f"https://suumo.jp/chintai/soba/kanagawa/sc_{ward.suumo_code}/?ts=1"
            tochidai_url = f"https://tochidai.info/mansion/kanagawa/{ward.tochidai_slug}/"
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
    out = ROOT / "data" / "collected" / "jphouse_yokohama_wards_sources.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    index = output_root / "index.md"
    index.write_text(
        "# jphouse 横滨市内各区塔楼数据｜2026年8月\n\n"
        + "\n".join(f"- {item['ward']}：{item['output']}/data_detail.md" for item in collected)
        + ("\n\n## 未生成\n" + "\n".join(f"- {item['ward']}：{item['error']}" for item in failed) if failed else "")
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"generated": len(collected), "failed": len(failed), "summary": str(out), "index": str(index)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Dict, Iterable, List

REQUIRED_COLUMNS = {
    "record_date", "market", "status", "prefecture", "ward", "building_name",
    "area_sqm", "amount_yen", "source_url", "verified_on", "rights_confirmed",
}
VALID_MARKETS = {"sale", "rental"}
VALID_STATUSES = {"listing", "closed"}


def read_records(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError("缺少必填字段: " + ", ".join(sorted(missing)))
        records = []
        for line_number, record in enumerate(reader, start=2):
            clean = {key: (value or "").strip() for key, value in record.items()}
            validate_record(clean, line_number)
            records.append(clean)
    return records


def validate_record(record: Dict[str, str], line_number: int) -> None:
    try:
        datetime.strptime(record["record_date"], "%Y-%m-%d")
        datetime.strptime(record["verified_on"], "%Y-%m-%d")
        float(record["area_sqm"])
        int(record["amount_yen"])
    except ValueError as error:
        raise ValueError(f"第 {line_number} 行日期或数字格式错误: {error}") from error
    if record["market"] not in VALID_MARKETS:
        raise ValueError(f"第 {line_number} 行 market 必须为 sale 或 rental")
    if record["status"] not in VALID_STATUSES:
        raise ValueError(f"第 {line_number} 行 status 必须为 listing 或 closed")
    if record["rights_confirmed"].lower() != "yes":
        raise ValueError(f"第 {line_number} 行未经权利确认，不能进入发布数据集")
    if not record["source_url"].startswith(("https://", "http://")):
        raise ValueError(f"第 {line_number} 行 source_url 必须是链接")


def normalize(records: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized = []
    for record in records:
        item = dict(record)
        item["month"] = record["record_date"][:7]
        item["price_per_sqm_yen"] = str(round(int(record["amount_yen"]) / float(record["area_sqm"])))
        normalized.append(item)
    return normalized


def write_csv(path: Path, records: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        raise ValueError("没有可输出的记录")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def make_report(records: List[Dict[str, str]], title: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    for record in records:
        groups[(record["month"], record["market"], record["status"])].append(record)

    monthly_rows = []
    for (month, market, status), group in sorted(groups.items()):
        amounts = [int(item["amount_yen"]) for item in group]
        ppsm = [int(item["price_per_sqm_yen"]) for item in group]
        monthly_rows.append({
            "month": month,
            "market": market,
            "status": status,
            "sample_count": str(len(group)),
            "median_amount_yen": str(round(median(amounts))),
            "median_price_per_sqm_yen": str(round(median(ppsm))),
        })
    write_csv(output_dir / "monthly_metrics.csv", monthly_rows)

    summary = {
        "title": title,
        "generated_on": date.today().isoformat(),
        "sample_count": len(records),
        "period": {"from": min(item["record_date"] for item in records), "to": max(item["record_date"] for item in records)},
        "groups": monthly_rows,
        "limitations": [
            "统计结果仅反映已人工核验并具备使用权限的样本，不代表完整市场。",
            "挂牌价与已成交价格分别统计，不得混用。",
            "发布前需人工复核数据、来源和合规性。",
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "xiaohongshu_draft.md").write_text(render_draft(summary), encoding="utf-8")


def render_draft(summary: Dict) -> str:
    lines = [f"# {summary['title']}", "", "吃饱饭，没事干，纯分享。", "", "【月度观察】"]
    for row in summary["groups"]:
        label = "出售" if row["market"] == "sale" else "出租"
        status = "已成交" if row["status"] == "closed" else "挂牌"
        lines.append(f"{row['month']}｜{label}/{status}｜{row['sample_count']}条｜¥{int(row['median_amount_yen']):,}｜¥{int(row['median_price_per_sqm_yen']):,}/㎡")
    lines.extend(["", "#东京房产 #港区 #塔楼 #日本租房 #日本买房"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="日本房产授权数据整理与草稿生成")
    commands = parser.add_subparsers(dest="command", required=True)
    normalize_parser = commands.add_parser("normalize", help="校验并标准化人工录入的数据")
    normalize_parser.add_argument("--input", required=True, type=Path)
    normalize_parser.add_argument("--output", required=True, type=Path)
    report_parser = commands.add_parser("report", help="从标准化数据生成统计和小红书草稿")
    report_parser.add_argument("--input", required=True, type=Path)
    report_parser.add_argument("--title", required=True)
    report_parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    records = read_records(args.input)
    normalized = normalize(records)
    if args.command == "normalize":
        write_csv(args.output, normalized)
    else:
        make_report(normalized, args.title, args.output_dir)


if __name__ == "__main__":
    main()

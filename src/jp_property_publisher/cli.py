import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional

from .pipeline import (
    STRICT_COLUMNS,
    load_policy,
    load_registry,
    load_snapshots,
    prepare_records,
    quality_check,
    read_strict_csv,
    write_csv as write_pipeline_csv,
)

REQUIRED_COLUMNS = {
    "record_date", "market", "status", "prefecture", "ward", "building_name",
    "area_sqm", "amount_yen", "source_url", "verified_on", "rights_confirmed", "data_class",
}
VALID_MARKETS = {"sale", "rental"}
VALID_STATUSES = {"listing", "closed"}
VALID_DATA_CLASSES = {
    "verified_observation", "scraped_aggregate", "modeled_estimate", "synthetic_fixture",
}


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
    if record["data_class"] not in VALID_DATA_CLASSES:
        raise ValueError(f"第 {line_number} 行 data_class 不受支持")
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
    if any(record.get("data_class") == "modeled_estimate" for record in records):
        raise ValueError("modeled_estimate rows cannot be rendered as factual metrics")
    output_dir.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    for record in records:
        groups[(record["month"], record["market"], record["status"], record["data_class"])].append(record)

    monthly_rows = []
    for (month, market, status, data_class), group in sorted(groups.items()):
        amounts = [int(item["amount_yen"]) for item in group]
        ppsm = [int(item["price_per_sqm_yen"]) for item in group]
        monthly_rows.append({
            "month": month,
            "market": market,
            "status": status,
            "data_class": data_class,
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
        lines.append(f"{row['month']}｜{label}/{status}｜{row['data_class']}｜{row['sample_count']}条｜¥{int(row['median_amount_yen']):,}｜¥{int(row['median_price_per_sqm_yen']):,}/㎡")
    lines.extend(["", "#东京房产 #港区 #塔楼 #日本租房 #日本买房"])
    return "\n".join(lines) + "\n"


METRIC_COLUMNS = [
    "prefecture",
    "ward",
    "market",
    "status",
    "data_class",
    "amount_unit",
    "currency",
    "month",
    "sample_count",
    "period_from",
    "period_to",
    "source_ids",
    "snapshot_ids",
    "snapshot_hashes",
    "snapshot_captured_at_from",
    "snapshot_captured_at_to",
    "median_amount_yen",
    "median_price_per_sqm_yen",
    "aggregation_method",
    "missing_value_policy",
    "trend_eligible",
    "trend_reason",
    "limitation",
]


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _summary_for_prepared(records: List[Dict[str, Any]], report: Any, policy: Dict[str, Any]) -> Dict[str, Any]:
    classes = sorted({str(record.get("data_class", "")) for record in records if record.get("data_class")})
    periods = [str(record.get("record_date", "")) for record in records if record.get("record_date")]
    trend_items = report.trend_eligibility
    return {
        "generated_on": date.today().isoformat(),
        "record_count": len(records),
        "data_class": classes[0] if len(classes) == 1 else "mixed",
        "data_classes": classes,
        "period": {"from": min(periods), "to": max(periods)} if periods else None,
        "groups": report.groups,
        "trend_policy_version": policy.get("version", "unknown"),
        "trend_eligible": bool(trend_items) and all(item.eligible for item in trend_items),
        "quality_status": "pass" if report.publishable else "blocked",
        "publication_scope": report.publication_scope,
        "limitations": [
            "指标按明确区域、租售类型、挂牌/成交状态、数据类别和单位分组。",
            "样本结果不代表完整市场；趋势必须满足版本化最低样本门槛。",
            "synthetic_fixture 仅用于离线流程验证，不代表真实市场。",
            "modeled_estimate 不进入事实指标或趋势。",
        ],
    }


def prepare_dataset(input_path: Path, registry_path: Path, snapshots_path: Path, policy_path: Path, output_dir: Path) -> int:
    """Prepare strict rows and always retain a quality report for audit."""

    records = read_strict_csv(input_path)
    registry = load_registry(registry_path)
    snapshots = load_snapshots(snapshots_path)
    policy = load_policy(policy_path)
    report = quality_check(records, registry, snapshots, policy)
    prepared = prepare_records(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared_fields = list(prepared[0].keys()) if prepared else list(STRICT_COLUMNS) + ["month", "price_per_sqm_yen"]
    write_pipeline_csv(output_dir / "prepared.csv", prepared, fieldnames=prepared_fields)
    metric_fields = list(dict.fromkeys(list(policy["trend"].get("group_by") or []) + METRIC_COLUMNS))
    write_pipeline_csv(output_dir / "monthly_metrics.csv", report.groups, fieldnames=metric_fields)
    quality_payload = report.to_dict()
    quality_payload["policy_version"] = policy.get("version", "unknown")
    quality_payload["input_record_count"] = len(records)
    _json_dump(output_dir / "quality_report.json", quality_payload)
    _json_dump(output_dir / "summary.json", _summary_for_prepared(records, report, policy))
    return 0 if report.publishable else 2


def quality_check_command(input_path: Path, registry_path: Path, snapshots_path: Path, policy_path: Path, output_path: Optional[Path]) -> int:
    records = read_strict_csv(input_path)
    registry = load_registry(registry_path)
    snapshots = load_snapshots(snapshots_path)
    policy = load_policy(policy_path)
    report = quality_check(records, registry, snapshots, policy)
    payload = report.to_dict()
    payload["policy_version"] = policy.get("version", "unknown")
    payload["input_record_count"] = len(records)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if output_path:
        _json_dump(output_path, payload)
    else:
        print(rendered)
    return 0 if report.publishable else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="日本房产授权数据整理与草稿生成")
    commands = parser.add_subparsers(dest="command", required=True)
    normalize_parser = commands.add_parser("normalize", help="校验并标准化人工录入的数据")
    normalize_parser.add_argument("--input", required=True, type=Path)
    normalize_parser.add_argument("--output", required=True, type=Path)
    report_parser = commands.add_parser("report", help="从标准化数据生成统计和小红书草稿")
    report_parser.add_argument("--input", required=True, type=Path)
    report_parser.add_argument("--title", required=True)
    report_parser.add_argument("--output-dir", required=True, type=Path)
    prepare_parser = commands.add_parser("prepare", help="准备严格多月份数据并运行离线质量门禁")
    prepare_parser.add_argument("--input", required=True, type=Path)
    prepare_parser.add_argument("--registry", required=True, type=Path)
    prepare_parser.add_argument("--snapshots", required=True, type=Path)
    prepare_parser.add_argument("--policy", required=True, type=Path)
    prepare_parser.add_argument("--output-dir", required=True, type=Path)
    quality_parser = commands.add_parser("quality-check", help="只运行严格数据质量检查")
    quality_parser.add_argument("--input", required=True, type=Path)
    quality_parser.add_argument("--registry", required=True, type=Path)
    quality_parser.add_argument("--snapshots", required=True, type=Path)
    quality_parser.add_argument("--policy", required=True, type=Path)
    quality_parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "prepare":
            return prepare_dataset(args.input, args.registry, args.snapshots, args.policy, args.output_dir)
        if args.command == "quality-check":
            return quality_check_command(args.input, args.registry, args.snapshots, args.policy, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    records = read_records(args.input)
    normalized = normalize(records)
    if args.command == "normalize":
        write_csv(args.output, normalized)
    else:
        make_report(normalized, args.title, args.output_dir)
    return 0


if __name__ == "__main__":
    main()

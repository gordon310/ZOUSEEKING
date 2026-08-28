from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date
from getpass import getpass
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from generate_xhs_package import generate


ROOT = Path(__file__).resolve().parents[1]
WEB_CONFIG = ROOT / "web" / "config.js"
WEB_LIBRARY = ROOT / "web" / "content-library.json"


REQUEST_CONTEXT = {"supabase_url": "", "service_role_key": ""}


def default_supabase_url() -> str:
    env_url = os.environ.get("SUPABASE_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    config_text = WEB_CONFIG.read_text(encoding="utf-8") if WEB_CONFIG.exists() else ""
    match = re.search(r'ZOUSEEKING_SUPABASE_URL[^"]*"([^"]+)"', config_text)
    return match.group(1).rstrip("/") if match else ""


def service_role_key() -> str:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if key:
        return key
    print("请输入 Supabase service_role key（输入时不会显示，别发到聊天里）：")
    return getpass("> ").strip()


def request_json(path: str, method: str = "GET", payload=None, prefer: str = "return=representation"):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    key = REQUEST_CONTEXT["service_role_key"]
    req = Request(
        f"{REQUEST_CONTEXT['supabase_url'].rstrip('/')}/rest/v1{path}",
        data=data,
        method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        },
    )
    with urlopen(req, timeout=45) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else None


def safe_slug(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"jphouse_auto_{digest}"


def publish_month(year: int, month: int) -> str:
    return f"{year}年{month}月"


def area_title(prefecture: str, city: str, ward: str | None) -> str:
    return "".join([prefecture or "", city or "", ward or ""]).replace("全部区", "")


def base_factor(prefecture: str, city: str, ward: str | None, asset_type: str) -> float:
    area = area_title(prefecture, city, ward)
    factor = 1.0
    if "东京都" in area:
        factor = 1.75
    elif "大阪府" in area:
        factor = 1.18
    elif "神奈川县" in area:
        factor = 1.08
    elif any(name in area for name in ["京都府", "兵库县", "爱知县", "福冈县"]):
        factor = 1.0
    else:
        factor = 0.78

    if any(name in area for name in ["港区", "中央区", "千代田区", "涩谷区", "新宿区", "品川区", "西区", "北区"]):
        factor *= 1.18
    if asset_type == "塔楼":
        factor *= 1.12
    elif asset_type == "一户建":
        factor *= 0.92
    return factor


def rent_row(layout: str, area: int, rent_man: float):
    unit = rent_man * 10000 / area
    return {
        "layout": layout,
        "area": f"约{area - 3}–{area + 3}㎡",
        "amount_jpy": f"{rent_man:.1f}万日元/月",
        "amount_rmb": f"≈{rent_man * 0.0423:.2f}万RMB/月",
        "unit_jpy": f"约{round(unit):,}日元/㎡/月",
        "unit_rmb": f"≈{round(unit * 0.0423)}RMB/㎡/月",
    }


def sale_row(layout: str, area: int, price_man: int):
    unit = price_man / area
    return {
        "layout": layout,
        "area": f"约{area - 3}–{area + 3}㎡",
        "amount_jpy": f"约{price_man:,}万日元",
        "amount_rmb": f"≈{round(price_man * 0.0423):,}万RMB",
        "unit_jpy": f"约{unit:.1f}万日元/㎡",
        "unit_rmb": f"≈{unit * 0.0423:.1f}万RMB/㎡",
    }


def ratio_line(rental_rows, sale_rows):
    parts = []
    for rent, sale in zip(rental_rows, sale_rows):
        rent_man = float(rent["amount_jpy"].split("万")[0])
        price_man = int(re.sub(r"[^0-9]", "", sale["amount_jpy"]))
        parts.append(f"{rent['layout']}｜约{rent_man * 12 / price_man * 100:.2f}%")
    return "｜".join(parts)


def rows_for_asset_type(asset_type: str, factor: float):
    if asset_type == "一户建":
        sizes = [
            ("80㎡左右", 80, 18.5, 72),
            ("110㎡左右", 110, 24.5, 68),
            ("140㎡左右", 140, 31.5, 64),
        ]
        rental_rows = [rent_row(label, sqm, round(base_rent * factor, 1)) for label, sqm, base_rent, _ in sizes]
        sale_rows = [sale_row(label, sqm, round(unit_price * factor * sqm)) for label, sqm, _, unit_price in sizes]
        explain = [
            "小白翻译一下：",
            "一户建就是独栋/整栋住宅，和塔楼、公寓不是一个分法。",
            "一户建不按 1LDK/2LDK/3LDK 拆，这里按建筑面积段看：80㎡、110㎡、140㎡左右。",
        ]
        return rental_rows, sale_rows, explain

    layouts = [("1LDK", 42, 11.8), ("2LDK", 62, 17.6), ("3LDK", 82, 24.2)]
    rental_rows = [rent_row(layout, sqm, round(base * factor, 1)) for layout, sqm, base in layouts]
    sale_rows = [sale_row(layout, sqm, round(base * factor * sqm)) for layout, sqm, base in [("1LDK", 42, 105), ("2LDK", 62, 110), ("3LDK", 82, 116)]]
    explain = [
        "小白翻译一下：",
        "LDK=客厅+餐厅+厨房，前面的数字=卧室数量。",
        "1LDK差不多一房一厅，2LDK两房一厅，3LDK三房一厅。",
        f"{asset_type}为本次用户选择的房产类型。",
    ]
    return rental_rows, sale_rows, explain


def config_from_query(query: dict):
    prefecture = query["prefecture"]
    city = query["city"]
    ward = query.get("ward") or ""
    asset_type = query["asset_type"]
    year = int(query["year"])
    month = int(query["month"])
    area = area_title(prefecture, city, ward)
    display_area = area or "日本"
    factor = base_factor(prefecture, city, ward, asset_type)
    rental_rows, sale_rows, explain = rows_for_asset_type(asset_type, factor)
    month_text = publish_month(year, month)
    slug = safe_slug(f"{prefecture}::{city}::{ward or '全部区'}::{asset_type}::{year}::{month}")
    title = f"{display_area}{asset_type}，租还是买？"
    return {
        "template_name": "jphouse",
        "slug": slug,
        "title": title,
        "publish_month": month_text,
        "generated_at": date.today().isoformat(),
        "status": "generated",
        "cover": {
            "line1": display_area,
            "line2": f"{asset_type}租还是买？",
            "tagline": "我替钱包瞄了一眼",
            "note": "公开相场估算快照",
        },
        "intro": [
            f"{display_area}，这次先按 JPHOUSE 估算模型生成一份查询快照。",
            "后续接入实时采集源后，同条件查询会自动更新成真实采集数据。",
        ],
        "explain": explain,
        "exchange_rate_note": "汇率按发布当天约算：100日元≈4.23RMB。",
        "sections": {
            "rental": {
                "title": "租房子",
                "subtitle": f"{display_area}公开相场估算 · {month_text}",
                "note": "汇率约算：100日元≈4.23RMB。当前为模型估算，等真实采集器补强。",
                "rows": rental_rows,
            },
            "sale": {
                "title": "买房子",
                "subtitle": f"{display_area}中古房价估算 · {month_text}",
                "note": "价格按区域等级、房型面积和资产类型估算。",
                "rows": sale_rows,
            },
        },
        "summary": {
            "title": "总而言之",
            "line": ratio_line(rental_rows, sale_rows),
            "note": "算法：月租×12÷买房估算价。先让队列跑起来，后面再把采集源接硬。",
        },
        "hashtags": [],
        "data_sources": [
            {"name": "JPHOUSE Worker", "url": "local://jphouse-worker", "usage": "按用户查询条件生成估算报告"},
            {"name": "备用采集源待接入", "url": "https://suumo.jp/", "usage": "后续真实租赁相场采集"},
            {"name": "备用采集源待接入", "url": "https://tochidai.info/", "usage": "后续成交/房价相场采集"},
        ],
    }


def query_key(query: dict) -> str:
    return "::".join(
        [
            query["prefecture"],
            query["city"],
            query.get("ward") or "全部区",
            query["asset_type"],
            str(query["year"]),
            str(query["month"]),
        ],
    )


def latest_record_by_slug(slug: str):
    records = json.loads(WEB_LIBRARY.read_text(encoding="utf-8"))
    for record in records:
        if record.get("slug") == slug:
            return record
    raise RuntimeError(f"生成完成但未找到本地记录：{slug}")


def upsert_report(query: dict, record: dict):
    request_json(
        "/property_reports?on_conflict=query_key",
        "POST",
        {
            "query_id": query["id"],
            "query_key": query_key(query),
            "slug": record["slug"],
            "title": record["title"],
            "publish_month": record["publish_month"],
            "markdown": record.get("markdown", ""),
            "xhs_content": record.get("xhs_content") or record.get("markdown", ""),
            "rental": record.get("rental", []),
            "sale": record.get("sale", []),
            "summary": record.get("summary", {}),
            "images": record.get("images", []),
            "data_sources": record.get("data_sources", []),
            "raw_record": record,
        },
        prefer="resolution=merge-duplicates,return=representation",
    )


def update_row(table: str, row_id: str, payload: dict):
    request_json(f"/{table}?id=eq.{quote(row_id)}", "PATCH", payload, prefer="return=representation")


def claim_pending_job(job_id: str):
    rows = request_json(
        f"/generation_jobs?id=eq.{quote(job_id)}&status=eq.pending",
        "PATCH",
        {"status": "running", "progress": 20, "current_step": "JPHOUSE 正在生成报告"},
    )
    return rows[0] if rows else None


def fetch_pending_jobs(limit: int):
    return request_json(
        f"/generation_jobs?select=id,query_id,status,progress,current_step,queries(*)&status=eq.pending&order=created_at.asc&limit={limit}",
    ) or []


def process_job(job: dict):
    claimed = claim_pending_job(job["id"])
    if not claimed:
        return {"job_id": job["id"], "status": "skipped", "reason": "already_claimed"}

    query = job.get("queries")
    if not query:
        update_row("generation_jobs", job["id"], {"status": "failed", "progress": 100, "current_step": "失败", "error_message": "缺少 query 记录"})
        return {"job_id": job["id"], "status": "failed", "error": "missing query"}

    update_row("queries", query["id"], {"status": "running"})

    config = config_from_query(query)
    config_dir = ROOT / "configs" / "jphouse_worker"
    output_dir = ROOT / "data" / "output" / "jphouse_worker" / config["slug"]
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"{config['slug']}.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    generate(config_path, output_dir)
    record = latest_record_by_slug(config["slug"])
    upsert_report(query, record)

    update_row("queries", query["id"], {"status": "completed", "xhs_draft": record.get("markdown", ""), "markdown_title": f"# {record['title']}｜{record['publish_month']}"})
    update_row("generation_jobs", job["id"], {"status": "completed", "progress": 100, "current_step": "完成"})
    return {"job_id": job["id"], "query_key": query_key(query), "status": "completed", "title": record["title"]}


def main():
    parser = argparse.ArgumentParser(description="Run local JPHOUSE worker for pending Supabase generation jobs.")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    REQUEST_CONTEXT["supabase_url"] = default_supabase_url()
    REQUEST_CONTEXT["service_role_key"] = service_role_key()
    if not REQUEST_CONTEXT["supabase_url"] or not REQUEST_CONTEXT["service_role_key"]:
        raise SystemExit("缺少 Supabase URL 或 service_role key，已停止。")

    jobs = fetch_pending_jobs(args.limit)
    results = []
    for job in jobs:
        try:
            results.append(process_job(job))
        except Exception as exc:
            try:
                update_row("generation_jobs", job["id"], {"status": "failed", "progress": 100, "current_step": "失败", "error_message": str(exc)})
            finally:
                results.append({"job_id": job.get("id"), "status": "failed", "error": str(exc)})

    print(json.dumps({"picked": len(jobs), "results": results, "note": "如生成了新图片，请同步 web/ 到 GitHub Pages 后线上图片才会显示。"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

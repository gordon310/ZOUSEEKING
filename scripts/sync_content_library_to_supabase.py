import json
import os
import re
from getpass import getpass
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WEB_LIBRARY = ROOT / "web" / "content-library.json"
WEB_CONFIG = ROOT / "web" / "config.js"


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


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def record_location(record):
    title = record.get("title", "")
    if title.startswith("东京"):
        return {"prefecture": "东京都", "city": "东京23区", "ward": title.removeprefix("东京").split("塔楼")[0]}
    if title.startswith("大阪"):
        return {"prefecture": "大阪府", "city": "大阪市", "ward": title.removeprefix("大阪").split("塔楼")[0]}
    if title.startswith("横滨"):
        return {"prefecture": "神奈川县", "city": "横滨市", "ward": title.removeprefix("横滨").split("塔楼")[0]}
    return {"prefecture": "", "city": "", "ward": ""}


def query_key(loc, asset_type, publish_month):
    match = re.match(r"([0-9]{4})年([0-9]{1,2})月", publish_month or "")
    year = match.group(1) if match else "2026"
    month = str(int(match.group(2))) if match else "8"
    return "::".join([loc["prefecture"], loc["city"], loc["ward"] or "全部区", asset_type, year, month])


def request_json(url, method="GET", payload=None):
    supabase_url = REQUEST_CONTEXT["supabase_url"]
    key = REQUEST_CONTEXT["service_role_key"]
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = Request(
        f"{supabase_url}/rest/v1{url}",
        data=data,
        method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
    )
    with urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else None


def main():
    REQUEST_CONTEXT["supabase_url"] = default_supabase_url()
    REQUEST_CONTEXT["service_role_key"] = service_role_key()
    if not REQUEST_CONTEXT["supabase_url"] or not REQUEST_CONTEXT["service_role_key"]:
        raise SystemExit("缺少 Supabase URL 或 service_role key，已停止同步。")
    records = json.loads(WEB_LIBRARY.read_text(encoding="utf-8"))
    synced = 0
    for record in records:
        loc = record_location(record)
        if not loc["prefecture"]:
            continue
        asset_type = record.get("asset_type") or ("塔楼" if "塔楼" in record.get("title", "") else "房产")
        key = query_key(loc, asset_type, record.get("publish_month"))
        match = re.match(r"([0-9]{4})年([0-9]{1,2})月", record.get("publish_month", ""))
        year = int(match.group(1)) if match else 2026
        month = int(match.group(2)) if match else 8
        query_rows = request_json(
            "/queries?on_conflict=query_key",
            "POST",
            {
                "query_key": key,
                "prefecture": loc["prefecture"],
                "city": loc["city"],
                "ward": loc["ward"],
                "asset_type": asset_type,
                "year": year,
                "month": month,
                "status": "completed",
                "markdown_title": f"# {record.get('title', '')}｜{record.get('publish_month', '')}",
                "xhs_draft": record.get("markdown", ""),
            },
        )
        query_id = query_rows[0]["id"] if query_rows else None
        request_json(
            "/property_reports?on_conflict=query_key",
            "POST",
            {
                "query_id": query_id,
                "query_key": key,
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
        )
        synced += 1
    print(json.dumps({"synced": synced}, ensure_ascii=False, indent=2))


REQUEST_CONTEXT = {"supabase_url": "", "service_role_key": ""}


if __name__ == "__main__":
    main()

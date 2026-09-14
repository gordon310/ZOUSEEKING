import json
import os
import re
from getpass import getpass
from pathlib import Path
from urllib.request import Request, urlopen

from backend.app.jphouse_service import normalize_query_ward


ROOT = Path(__file__).resolve().parents[1]
WEB_LIBRARY = ROOT / "web" / "content-library.json"
WEB_CONFIG = ROOT / "web" / "config.js"


def _service_headers(key: str) -> dict[str, str]:
    headers = {"apikey": key}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


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
    """Read the canonical C-end location fields; never infer them from title text."""

    prefecture = str(record.get("prefecture") or "").strip()
    city = str(record.get("city") or "").strip()
    ward = normalize_query_ward(record.get("ward"))
    if not prefecture or not city:
        return {"prefecture": "", "city": "", "ward": ""}
    return {"prefecture": prefecture, "city": city, "ward": ward}


def query_key(loc, asset_type, publish_month):
    match = re.match(r"([0-9]{4})年([0-9]{1,2})月", publish_month or "")
    year = match.group(1) if match else "2026"
    month = str(int(match.group(2))) if match else "8"
    return "::".join([loc["prefecture"], loc["city"], normalize_query_ward(loc.get("ward")), asset_type, year, month])


def request_json(url, method="GET", payload=None):
    supabase_url = REQUEST_CONTEXT["supabase_url"]
    key = REQUEST_CONTEXT["service_role_key"]
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = Request(
        f"{supabase_url}/rest/v1{url}",
        data=data,
        method=method,
        headers={
            **_service_headers(key),
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
        synced += 1
    print(json.dumps({"synced_queries": synced, "reports_written": 0, "report_generation": "authenticated_regular_path_required"}, ensure_ascii=False, indent=2))


REQUEST_CONTEXT = {"supabase_url": "", "service_role_key": ""}


if __name__ == "__main__":
    main()

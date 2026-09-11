#!/usr/bin/env python3
"""Render the deployment-time frontend configuration from a dotenv file."""

import argparse
import json
import sys
from pathlib import Path


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def render_config(values: dict[str, str]) -> str:
    phase = values.get("RELEASE_PHASE") or "consumer_active"
    api_base = values.get("FRONTEND_API_BASE_URL") or "https://api.zoubeacon.com"
    business_operations = phase != "consumer_intake_preview"
    supabase_url = json.dumps(values["SUPABASE_URL"])
    supabase_anon_key = json.dumps(values["SUPABASE_ANON_KEY"])
    phase_json = json.dumps(phase)
    api_base_json = json.dumps(api_base)
    return (
        f"window.ZOUSEEKING_API_BASE_URL = {api_base_json};\n"
        f"window.ZOUSEEKING_SUPABASE_URL = {supabase_url};\n"
        f"window.ZOUSEEKING_SUPABASE_ANON_KEY = {supabase_anon_key};\n"
        "window.ZOUSEEKING_RELEASE_SCOPE = Object.freeze({\n"
        f"  phase: {phase_json},\n"
        f"  businessOperations: {str(business_operations).lower()},\n"
        f"  adminOperations: {str(business_operations).lower()},\n"
        "});\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="deploy/.env")
    parser.add_argument("--out", default="web/config.js")
    args = parser.parse_args()

    env_path = Path(args.env)
    out_path = Path(args.out)
    try:
        values = parse_env(env_path)
    except OSError as exc:
        print(f"error: unable to read {env_path}: {exc}", file=sys.stderr)
        return 1

    missing = [
        key
        for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY")
        if not values.get(key) or ("<" in values[key] and ">" in values[key])
    ]
    if missing:
        print(f"error: missing required {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        out_path.write_text(render_config(values), encoding="utf-8")
    except OSError as exc:
        print(f"error: unable to write {out_path}: {exc}", file=sys.stderr)
        return 1

    phase = values.get("RELEASE_PHASE") or "consumer_active"
    api_base = values.get("FRONTEND_API_BASE_URL") or "https://api.zoubeacon.com"
    print(f"wrote {out_path} (phase={phase}, api={api_base})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

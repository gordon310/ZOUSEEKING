#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="${APP_ROOT:-/opt/zouseeking}"
PYTHON_BIN="${PYTHON_BIN:-$APP_ROOT/backend/.venv/bin/python}"
KEY_FILE="${MLIT_KEY_FILE:-/etc/zouseeking/mlit-api-key}"
LOG_FILE="${MLIT_REFRESH_LOG:-/var/log/zouseeking-mlit-refresh.log}"

umask 077
mkdir -p "$(dirname "$LOG_FILE")"
exec >>"$LOG_FILE" 2>&1

started_at="$(date --iso-8601=seconds)"
status=0
trap 'status=$?; printf "%s status=%s\n" "$(date --iso-8601=seconds)" "$status"; exit "$status"' EXIT

printf "%s start app_root=%s\n" "$started_at" "$APP_ROOT"
if [[ ! -r "$KEY_FILE" ]]; then
  printf "%s missing unreadable key file\n" "$(date --iso-8601=seconds)" >&2
  exit 1
fi
if [[ "$(stat -c %a "$KEY_FILE")" != "600" ]]; then
  printf "%s key file must have mode 600\n" "$(date --iso-8601=seconds)" >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  printf "%s python interpreter is not executable\n" "$(date --iso-8601=seconds)" >&2
  exit 1
fi

export PYTHONPATH="$APP_ROOT"
export MLIT_API_KEY="$(<"$KEY_FILE")"
if [[ -z "$MLIT_API_KEY" ]]; then
  printf "%s key file is empty\n" "$(date --iso-8601=seconds)" >&2
  exit 1
fi

cd "$APP_ROOT"
current_year="$(date +%Y)"
previous_year=$((current_year - 1))
for year in "$current_year" "$previous_year"; do
  printf "%s refresh year=%s prefectures=13,27,15\n" "$(date --iso-8601=seconds)" "$year"
  "$PYTHON_BIN" scripts/import_mlit_transactions.py \
    --prefecture 13 --prefecture 27 --prefecture 15 \
    --year "$year"
  printf "%s refresh year=%s complete\n" "$(date --iso-8601=seconds)" "$year"
done

printf "%s refresh summary years=%s,%s status=success\n" "$(date --iso-8601=seconds)" "$current_year" "$previous_year"

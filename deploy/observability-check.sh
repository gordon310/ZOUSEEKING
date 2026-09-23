#!/usr/bin/env bash
# Read-only production check: Compose state, HTTP readiness and PostgreSQL metrics.
set -u -o pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/zouseeking}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
DATABASE_URL="${DATABASE_URL:?DATABASE_URL is required}"
API_HEALTH_URL="${API_HEALTH_URL:-https://api.zoubeacon.com/health/ready}"
API_CONTAINER="${API_CONTAINER:-deploy-api-1}"
EXPECTED_SERVICES="${JPP_OBSERVABILITY_SERVICES:-api report-worker nginx}"
BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-/var/backups/zouseeking}"
BACKUP_FRESHNESS_HOURS="${BACKUP_FRESHNESS_HOURS:-36}"
failed=0
summary=()

problem() { summary+=("$1"); failed=1; }

if [[ -n "${JPP_COMPOSE_RUNNING_SERVICES:-}" ]]; then
  # Local test seam only; production leaves this unset and executes Compose.
  running="$JPP_COMPOSE_RUNNING_SERVICES"
elif [[ -d "$DEPLOY_DIR" ]]; then
  running="$(cd "$DEPLOY_DIR" && docker compose -f "$COMPOSE_FILE" ps --services --filter status=running 2>&1)" || problem "compose_ps_error"
  for service in $EXPECTED_SERVICES; do
    if ! grep -Fxq "$service" <<<"$running"; then problem "container_not_running:$service"; fi
  done
else
  problem "deploy_directory_missing:$DEPLOY_DIR"
fi

if ! health="$(curl --fail --silent --show-error --max-time 10 "$API_HEALTH_URL" 2>&1)"; then
  problem "api_health_failed:$health"
fi

backup_artifact=""
backup_mtime=""
if [[ -n "${BACKUP_S3_BUCKET:-}" && -n "${BACKUP_S3_ENDPOINT:-}" && -n "${BACKUP_S3_REGION:-}" && -n "${BACKUP_S3_ACCESS_KEY_ID:-}" && -n "${BACKUP_S3_SECRET_ACCESS_KEY:-}" ]]; then
  backup_prefix="${BACKUP_S3_PREFIX:-zouseeking/database}"
  if ! backup_artifact="$(AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_ACCESS_KEY" AWS_DEFAULT_REGION="$BACKUP_S3_REGION" docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION amazon/aws-cli:2.27.1 --endpoint-url "$BACKUP_S3_ENDPOINT" s3api list-objects-v2 --bucket "$BACKUP_S3_BUCKET" --prefix "$backup_prefix" --query 'reverse(sort_by(Contents[?ends_with(Key, `.manifest.json`)],&LastModified))[0].[Key,LastModified]' --output text 2>&1)"; then
    problem "backup_artifact_s3_list_failed:$backup_artifact"
  elif [[ -z "$backup_artifact" || "$backup_artifact" == "None" ]]; then
    problem "backup_artifact_missing:s3"
  else
    backup_mtime="${backup_artifact##*$'\t'}"
  fi
else
  if [[ -d "$BACKUP_LOCAL_DIR" ]]; then
    backup_artifact="$(find "$BACKUP_LOCAL_DIR" -maxdepth 1 -type f -name 'zouseeking-*.manifest.json' -printf '%T@\t%p\n' 2>/dev/null | sort -nr | head -n 1)"
  fi
  if [[ -z "$backup_artifact" ]]; then
    problem "backup_artifact_missing:local:$BACKUP_LOCAL_DIR"
  else
    backup_mtime="${backup_artifact%%$'\t'*}"
    backup_path="${backup_artifact#*$'\t'}"
    [[ -f "${backup_path%.manifest.json}.dump" ]] || problem "backup_artifact_dump_missing:$backup_path"
  fi
fi
if [[ -n "$backup_mtime" ]]; then
  if backup_epoch="$(date -d "$backup_mtime" +%s 2>/dev/null)"; then
    backup_age_hours=$(( ($(date +%s) - backup_epoch) / 3600 ))
    printf 'backup_artifact=%s backup_age_hours=%s threshold_hours=%s\n' "$backup_artifact" "$backup_age_hours" "$BACKUP_FRESHNESS_HOURS"
    if (( backup_age_hours > BACKUP_FRESHNESS_HOURS )); then problem "backup_artifact_stale:${backup_age_hours}h"; fi
  else
    problem "backup_artifact_timestamp_invalid:$backup_mtime"
  fi
fi

read -r -d '' DATABASE_METRICS_PYTHON <<'PYTHON' || true
import asyncio
import os

import asyncpg


QUERIES = (
    ("failed", "select count(*) from public.report_generation_outbox where status='failed'"),
    ("zombie_running", "select count(*) from public.report_generation_outbox where status='running' and claimed_at < now() - interval '15 minutes'"),
    ("pending_due", "select count(*) from public.report_generation_outbox where status='pending' and next_attempt_at <= now()"),
    ("usage_events_latest", "select coalesce(max(created_at)::text, 'never') from public.usage_events"),
    ("reports_latest", "select coalesce(max(created_at)::text, 'never') from public.property_reports"),
)


async def main() -> None:
    connection = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await connection.execute("set default_transaction_read_only = on")
        if await connection.fetchval("show transaction_read_only") != "on":
            raise RuntimeError("database connection did not enter read-only mode")
        for key, query in QUERIES:
            print(f"{key}={await connection.fetchval(query)}")
    finally:
        await connection.close()


asyncio.run(main())
PYTHON

if ! metrics="$(docker exec -e DATABASE_URL "$API_CONTAINER" python -c "$DATABASE_METRICS_PYTHON" 2>&1)"; then
  problem "database_read_failed:$metrics"
else
  printf '%s\n' "$metrics"
  while IFS='=' read -r key value; do
    case "$key" in
      failed|zombie_running|pending_due) [[ "$value" == "0" ]] || problem "queue_$key=$value" ;;
    esac
  done <<<"$metrics"
fi

if (( failed )); then
  printf 'OBSERVABILITY_ALERT %s\n' "${summary[*]}" >&2
  exit 1
fi
printf 'OBSERVABILITY_OK services="%s" health="%s"\n' "$EXPECTED_SERVICES" "$API_HEALTH_URL"

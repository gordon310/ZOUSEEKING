#!/usr/bin/env bash
# Read-only production check: Compose state, HTTP readiness and PostgreSQL metrics.
set -u -o pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/zouseeking}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
DATABASE_URL="${DATABASE_URL:?DATABASE_URL is required}"
API_HEALTH_URL="${API_HEALTH_URL:-http://127.0.0.1:8000/health/ready}"
EXPECTED_SERVICES="${JPP_OBSERVABILITY_SERVICES:-api report-worker nginx}"
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

sql="select 'failed=' || count(*) from public.report_generation_outbox where status='failed';
select 'zombie_running=' || count(*) from public.report_generation_outbox where status='running' and claimed_at < now() - interval '15 minutes';
select 'pending_due=' || count(*) from public.report_generation_outbox where status='pending' and next_attempt_at <= now();
select 'usage_events_latest=' || coalesce(max(created_at)::text, 'never') from public.usage_events;
select 'reports_latest=' || coalesce(max(created_at)::text, 'never') from public.property_reports;"
if ! metrics="$(PGOPTIONS='-c default_transaction_read_only=on' psql "$DATABASE_URL" -X -q -At -v ON_ERROR_STOP=1 -c "BEGIN READ ONLY; $sql COMMIT;" 2>&1)"; then
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

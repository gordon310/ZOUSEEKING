# Lightsail production-configuration contract

deployment status: NOT_EXECUTED

## Scope and non-claims

This is the configuration contract for the Lightsail Docker Compose deployment. It records repository configuration and static checks only; it is not a production-readiness, deployed, or exercised-production claim. Production status remains `NEEDS_PROD_EVIDENCE`.

## Deployment topology

| Service | Purpose and build source | Start command | Exposure and dependencies | Operating mode |
| --- | --- | --- | --- | --- |
| `api` | FastAPI API; `deploy/Dockerfile.backend` | Dockerfile CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000` | `expose: 8000`; external database; no Compose dependency declared | resident |
| `jpsskill` | Optional AI analysis service; `/opt/jppskill/Dockerfile` | image Dockerfile default command | `expose: 8100`; API may call it, but no Compose dependency declared | opt-in: `--profile ai` |
| `worker` | Collection worker; `deploy/Dockerfile.backend` | `python /app/scripts/collection_worker.py --loop 0 --interval 10` | internal only; external database and collected-data mount | resident |
| `report-worker` | Durable report outbox worker; `deploy/Dockerfile.backend` | `python -m app.report_worker` | internal only; external database and collected-data mount | resident |
| `scheduler` | Collection, QA, and retention loop; `deploy/Dockerfile.backend` | shell hourly loop running scheduler, sweep, and retention scripts | internal only; external database and collected-data mount | resident |
| `nginx` | TLS/public reverse proxy and static sites; `nginx:alpine` image | image default command | publishes `80:80` and `443:443`; declared `depends_on: api` | resident |

The authoritative topology is `deploy/docker-compose.prod.yml`.

## Staging versus production boundary

`render.yaml` is staging-only: it defines `zouseeking-api-staging` and `zouseeking-web-staging`, including `ENVIRONMENT=staging`. Its authoritative files are `render.yaml` and Render-managed secret settings. `deploy/docker-compose.prod.yml`, `deploy/.env.example`, `deploy/README.md`, `deploy/observability-check.sh`, and `deploy/systemd/` are the Lightsail production authority.

They must not share configuration files or reference each other. Render uses its service manifest and managed environment model; Lightsail uses Compose, host-mounted paths, operator-controlled `.env`, and systemd environment files. Mixing them could direct a staging deployment at production infrastructure or leak production-only credentials into Render.

## Controlled exception: the opt-in jpsskill service

`jpsskill` is an opt-in AI component built from the repository-external `/opt/jppskill` context. It declares `profiles: ["ai"]`, so it does not participate in the default production stack. It uses its own uncommitted `deploy/jpsskill.env`; all resident main-stack services share `deploy/.env`.

This is the only permitted `env_file` exception. Any new exception must be added to this contract and to the static guard test at the same time.

## Environment variable contract

Classifications are limited to `production_required`, `production_optional`, `ci_only`, and `runtime_injected`. Values marked secret must be supplied by a controlled provider, never committed.

| Key | Classification | Default or requirement | Description |
| --- | --- | --- | --- |
| `ABUSE_HASH_SALT` | production_required | required; secret | Hash salt for abuse controls. |
| `ADMIN_ENABLED` | production_required | required; `false` closes admin | Explicit admin gate; default `false` keeps the admin platform closed (`backend/app/admin/service.py:1236`). |
| `APP_VERSION` | production_required | required | Deployed application version. |
| `BACKUP_PG_CLIENT_IMAGE` | production_optional | code default when unset | PostgreSQL client image for backup work. |
| `BACKUP_RETENTION_DAYS` | production_optional | code default when unset | Local backup-retention period. |
| `BACKUP_S3_ACCESS_KEY_ID` | production_optional | required when uploading; secret | 备份目标凭据 id;与 bucket 范围绑定 |
| `BACKUP_S3_BUCKET` | production_optional | required when uploading | 目标桶名 |
| `BACKUP_S3_ENDPOINT` | production_optional | required when uploading | S3 兼容端点(R2:`https://<account-id>.r2.cloudflarestorage.com`) |
| `BACKUP_S3_PREFIX` | production_optional | default `zouseeking/database` | 对象键前缀 |
| `BACKUP_S3_REGION` | production_optional | `auto` for R2 | 签名区域;R2 用 `auto` |
| `BACKUP_S3_RETENTION_DAYS` | production_optional | falls back to `BACKUP_RETENTION_DAYS` (14) | 远端备份保留天数 |
| `BACKUP_S3_SECRET_ACCESS_KEY` | production_optional | required when uploading; secret | 备份目标凭据密钥 |
| `BILLING_CANCEL_URL` | production_required | required | Stripe cancellation redirect URL. |
| `BILLING_PORTAL_RETURN_URL` | production_required | required | Stripe portal return URL. |
| `BILLING_SUCCESS_URL` | production_required | required | Stripe success redirect URL. |
| `DATABASE_URL` | production_required | required; secret | Database connection string. |
| `ENVIRONMENT` | production_required | required | Environment identity, production on Lightsail. |
| `GITHUB_REF_NAME` | runtime_injected | CI injected; do not set in `.env` | Source ref recorded by release evidence. |
| `GITHUB_SHA` | runtime_injected | CI injected; do not set in `.env` | Source revision recorded by release evidence. |
| `INTAKE_BUCKET` | production_required | required | Server-owned intake storage bucket. |
| `INTERNAL_DIAGNOSTICS_TOKEN` | production_required | required; secret | Internal diagnostics authorization token. |
| `INVITE_REGISTER_RATE_LIMIT_PER_HOUR` | production_optional | default `5` | Invite-registration hourly rate limit. |
| `JPPSKILL_BASE_URL` | production_optional | required when AI enabled | Internal JPP skill endpoint; supplied by the main-stack `.env` and read by the `api` service. |
| `JPPSKILL_TIMEOUT_SECONDS` | production_optional | default configured by deployment | JPP skill request timeout; supplied by the main-stack `.env` and read by the `api` service. |
| `LICENSED_AGGREGATE_DIR` | production_optional | unset when disabled | Authorized aggregate-input directory. |
| `LOG_LEVEL` | production_optional | code default when unset | Application logging threshold. |
| `LOG_THIRD_PARTY_LEVEL` | production_optional | code default when unset | Dependency logging threshold. |
| `MLIT_API_KEY` | production_optional | required for MLIT imports; secret | MLIT import credential. |
| `MLIT_XIT001_URL` | production_optional | code default when unset | MLIT source endpoint override. |
| `OUTBOUND_BACKOFF_BASE_SECONDS` | production_optional | default `0.25` | Retry backoff base. |
| `OUTBOUND_MAX_ATTEMPTS` | production_optional | default `2` | Bounded outbound retry count. |
| `OUTBOUND_TIMEOUT_SECONDS` | production_optional | default `8.0` | Outbound request timeout. |
| `OUTBOUND_TRANSIENT_STATUS_CODES` | production_optional | default `408,425,429,500,502,503,504` | Comma-separated retryable status codes. |
| `PRICING_CACHE_TTL_SECONDS` | production_optional | code default when unset | Pricing-catalog cache lifetime. |
| `PROVENANCE_LAST_SUCCESS_AT` | production_optional | workflow supplied | Latest successful provenance retrieval timestamp. |
| `PROVENANCE_PARSER_VERSION` | production_optional | workflow supplied | Provenance parser version. |
| `PROVENANCE_STATUS` | production_optional | workflow supplied | Provenance status. |
| `QUERY_RATE_LIMIT_PER_HOUR` | production_optional | default `20` | Member query hourly rate limit. |
| `RECOGNITION_AI_ENABLED` | production_optional | default `false` | Enables AI recognition only when approved. |
| `RELEASE_PHASE` | production_required | required | Server-enforced release phase. |
| `RENOVATION_VISION_API_TOKEN` | production_optional | required when enabled; secret | Renovation-vision provider credential. |
| `RENOVATION_VISION_API_URL` | production_optional | required when enabled | Renovation-vision provider endpoint. |
| `REPORT_WORKER_ONCE` | production_optional | default continuous mode | One-shot report-worker mode for operator or local use. |
| `REVERSE_GEOCODER_TIMEOUT_SECONDS` | production_optional | code default when unset | Reverse-geocoder timeout. |
| `REVERSE_GEOCODER_URL` | production_optional | code default when unset | Reverse-geocoder endpoint. |
| `STRIPE_PRICE_IDS` | production_required | required | Server-owned Stripe price-ID mapping. |
| `STRIPE_SECRET_KEY` | production_required | required; secret | Stripe server secret key. |
| `STRIPE_WEBHOOK_SECRET` | production_required | required; secret | Stripe webhook verification secret. |
| `SUPABASE_ANON_KEY` | production_required | required | Supabase publishable/anon key, safe only with correct RLS. |
| `SUPABASE_SERVICE_ROLE_KEY` | production_required | required; secret | Supabase privileged server credential. |
| `SUPABASE_STAGING_REF` | ci_only | staging tooling only | Staging project reference for schema inspection. |
| `SUPABASE_URL` | production_required | required | Supabase project URL. |

## Secret handling

Secrets include `DATABASE_URL`, `ABUSE_HASH_SALT`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, `INTERNAL_DIAGNOSTICS_TOKEN`, `MLIT_API_KEY`, `RENOVATION_VISION_API_TOKEN`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `SUPABASE_SERVICE_ROLE_KEY`. `.env` is not committed; real values belong only in a controlled provider or restricted host environment file. `scripts/ci/secret_scan.py` is a Release Gate check for committed secret-shaped values, not proof that a host is correctly configured. Rotation requires updating the controlled provider, restarting the affected service, revoking the prior credential, and recording operational verification without exposing the value.

## Health and readiness

`/health/live` is the liveness endpoint for process reachability. `/health/ready` is the readiness endpoint used by staging and the production observability probe; it is the appropriate endpoint for traffic readiness rather than a declaration that the service has been exercised. `deploy/observability-check.sh` is a read-only production probe: it checks expected Compose services, public readiness, and read-only queue/freshness signals. No production probe has been run for this contract, so status is `NEEDS_PROD_EVIDENCE`.

## Known gaps

- Code-read keys missing from the prior `deploy/.env.example`: `ADMIN_ENABLED`, `BACKUP_PG_CLIENT_IMAGE`, `BACKUP_RETENTION_DAYS`, `GITHUB_REF_NAME`, `GITHUB_SHA`, `LICENSED_AGGREGATE_DIR`, `LOG_LEVEL`, `LOG_THIRD_PARTY_LEVEL`, `MLIT_API_KEY`, `MLIT_XIT001_URL`, `OUTBOUND_TRANSIENT_STATUS_CODES`, `PRICING_CACHE_TTL_SECONDS`, `PROVENANCE_LAST_SUCCESS_AT`, `PROVENANCE_PARSER_VERSION`, `PROVENANCE_STATUS`, `RENOVATION_VISION_API_TOKEN`, `RENOVATION_VISION_API_URL`, `REPORT_WORKER_ONCE`, `REVERSE_GEOCODER_TIMEOUT_SECONDS`, `REVERSE_GEOCODER_URL`, `SUPABASE_STAGING_REF`, `OUTBOUND_TIMEOUT_SECONDS`, `OUTBOUND_MAX_ATTEMPTS`, `OUTBOUND_BACKOFF_BASE_SECONDS`, `QUERY_RATE_LIMIT_PER_HOUR`, and `INVITE_REGISTER_RATE_LIMIT_PER_HOUR`.
- The measured production `deploy/.env` lacked `ADMIN_ENABLED` (default `false`, which closes admin), `QUERY_RATE_LIMIT_PER_HOUR` (default `20`), and `INVITE_REGISTER_RATE_LIMIT_PER_HOUR` (default `5`).
- Closed: the Cloudflare R2 backup target was configured and tested for upload, download, list, and delete, with a SHA-256 round trip match. A real production backup upload has not run; that evidence remains `NEEDS_PROD_EVIDENCE`.
- Staging and production use different Supabase projects. Production alert delivery and alert/restore exercises are unverified and remain `NEEDS_PROD_EVIDENCE`.

# Production reliability contract

## Scope and non-claims

This document records repository-level reliability controls. It is not a production-readiness statement. Production alert delivery, provider routing, and an incident/restore exercise remain `NOT_EXECUTED`.

## Structured logging and correlation

The API process configures one stdout JSON handler. Its vocabulary matches the worker logger: `ts`, `level`, `service`, `event`, plus safe structured fields. The primary request fields are:

| Field | Meaning |
| --- | --- |
| `ts` | UTC ISO-8601 timestamp with `Z` suffix |
| `level` | Python log level |
| `service` | API or worker service name |
| `event` | Stable event name |
| `request_id` | Accepted or generated request correlation ID |
| `duration_ms` | Completed request duration in milliseconds |

Inbound `X-Request-Id` is accepted only when it is 1--128 ASCII letters, digits, `.`, `_`, or `-`; otherwise an UUID4 hex ID is generated. The response writes the same ID to `X-Request-Id`. Worker events continue to correlate outbox/job work through their worker and job identifiers.

## Third-party log records

Records outside the `app.*` namespace below `LOG_THIRD_PARTY_LEVEL` are dropped; the default threshold is `WARNING`. Records at or above the threshold are emitted as `event="log"` with `logger` and a redacted `message`. Retaining the redacted message preserves useful third-party diagnostics while avoiding credential and email leakage; emitting a metadata-only skeleton would lose the diagnostic value entirely. Raising `LOG_THIRD_PARTY_LEVEL` to `INFO` significantly increases log volume.

## Redaction rules

Request bodies, query strings, authorization headers, raw source payloads, exception messages, and tracebacks must never be logged. API structured logging permits scalar fields only and replaces all other values with `<redacted>`. `redact()` removes email addresses, `sb_` tokens, `sk_live_`/`sk_test_` tokens, JWT-shaped `eyJ...` tokens, and `access_token=` or `apikey=` URL query values. Nested untrusted mappings are redacted recursively and stop after depth 6.

## Outbound timeouts, retries, cancellation

`backend.app.timeouts` centralizes these values. Their defaults retain the pre-existing standard-library request timeout behavior.

| Setting | Environment variable | Default |
| --- | --- | --- |
| Default outbound timeout | `OUTBOUND_TIMEOUT_SECONDS` | `8.0` seconds |
| Transient HTTP status list | `OUTBOUND_TRANSIENT_STATUS_CODES` | `408,425,429,500,502,503,504` |
| Maximum attempts | `OUTBOUND_MAX_ATTEMPTS` | `2` |
| Exponential backoff base | `OUTBOUND_BACKOFF_BASE_SECONDS` | `0.25` seconds |
| Third-party log threshold | `LOG_THIRD_PARTY_LEVEL` | `WARNING` |

Retries are only enabled for confirmed idempotent reads: Supabase Auth user lookup and GSI reverse geocoding. Retryable failures are transport failures and the listed HTTP status codes; delay uses 0.5--1.5 jitter. `abortable_sleep()` propagates async cancellation unchanged.

The following calls deliberately do **not** auto-retry because they write, submit, or have uncertain idempotency: invite Admin user creation, intake object upload and delete, vision-provider POST, recognition POST, Supabase Admin logout/delete, and all Stripe billing gateway calls. Billing retains its injectable 30-second default and does not use retries.

## Rate limiting

Two layers are independent. Account entitlement consumption uses `consume_current_entitlement`; abuse-source limits use PostgreSQL-backed `shared_rate_limits` through [`backend/app/rate_limit.py`](../backend/app/rate_limit.py). UI display is not an authorization or quota boundary.

## Dependency audit

Release Gate requires `pip-audit` and `npm audit`. Re-run locally with the project’s release-gate commands or directly:

```bash
backend/.venv/bin/pip-audit
npm audit
```

## Alerts and on-call

Alert conditions and the on-call response path are maintained in [operations/oncall.md](operations/oncall.md); this document intentionally does not duplicate that runbook.

## Known gaps

- Production alert delivery is not verified.
- No Alertmanager/PagerDuty-class provider routing is wired.
- No production incident or restore drill has been executed.

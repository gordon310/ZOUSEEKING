# Report entitlement security patch (2026-10-11)

Base: PR #4 `codex/launch-closure`, `c35379624ed05136ae8bace2d945c3faa9e0bee1`.
This is a local, unpushed candidate. No production database, payments or deployment were touched.

## Boundary

- Cached query responses, completed job polling and dedicated report reads share a non-consuming entitlement gate. A free owner retains the basic preview; full report content requires an exact paid single-report order or a persisted positive report-credit consumption event for that owner/report.
- An unused monthly balance is not an unlock. Reading, polling, downloading and cache reuse do not spend credits. Successful full report generation may consume one existing C Plus monthly report credit; insufficient data does not. Exhaustion leaves a locked report and cannot charge overage or turn a generated report into a failed job.
- Consumption checks the live personal subscription, not a stale profile tier or an organization's plan. It serializes report/ledger writes, honors reservations, and preserves the original event's period for retries.
- Query and free-preview actions use the same currently-effective configured query period: existing free-plan daily and Plus-plan monthly definitions. No quota amount or product price is added or changed. This query allowance is separate from the monthly report-credit allowance.
- Historical `report:<key>` and `c-plus-report:<key>` consumption fingerprints are recognized only for a positive server-owned consume event in the exact user's scope (matching actor or historical NULL actor). A registry key, free capacity, another user, another report or a non-consume event is not evidence. No mass unlock/backfill is performed. Ambiguous historical records remain locked pending an authorized audit.
- Direct authenticated SQL/REST access is restricted to an owner-scoped preview allowlist. The compatibility view remains security-invoker and explicitly locked. Full table/view reads cannot expose premium/raw fields; service-role workers retain full access. Frontend adapters preserve the locked flag rather than rendering a preview as an unlocked report.

## Deployment and rollback requirements

1. Review the final diff and actual test evidence; recheck PR head and reconcile any intervening changes before publishing.
2. Before any separately authorized migration, take an approved recoverable database backup and verify grants/current view dependencies against the release candidate. Do not edit applied migrations.
3. Apply the new forward migration first (or in a controlled release window), then deploy the API/frontend together. The migration intentionally denies direct full-report reads even for paid users; their full report is served by the authenticated API. Existing frontend can show a locked view during the transition. API-only deployment does not close direct REST access.
4. Verify anonymous, unpaid owner, paid/consumed owner, another user, and service-role identities through both API and Supabase REST. Confirm no new usage event on reads/downloads and confirm existing free history/preview remains available.
5. Keep the report access restriction if application rollback is needed. Do not restore broad SELECT grants or the old full-content view. Forward-fix incompatibilities; database rows are not removed by this migration. A rollback to the old API would reintroduce query/job leakage and is not a safe rollback by itself.

This patch is not a claim that the live site is fixed or ready to launch. Production application of the migration, current release gates, payment acceptance and deployment remain separately authorized work.

## Verification

All database evidence uses synthetic fixtures in a disposable local PostgreSQL 17.11 instance. No external provider authentication or real payment was exercised.

- Guarded Python aggregate: **1100 passed, 1 skipped**, 2 existing deprecation warnings. All 55 canonical migrations were applied to the local test databases. Six tests in `tests/unit/test_staging_realtime_quota_acceptance.py` were explicitly excluded after its unmocked staging-script path attempted an external example-domain request. The successful aggregate disabled inherited proxies and blocked non-loopback DNS/socket connections before transmission. The sole skip is the live Supabase REST four-identity test because its API/keys were not configured; real SQL identity matrices ran successfully.
- New focused real-PostgreSQL tests: **39 report-access + 19 quota + 3 preview-boundary integration cases**, including 12 simultaneous requests for one report, competing reports for the last credit, key/fingerprint collision races, zero/reserved capacity, expiry and month reset, paid/consumed historical access, corrupt ownership, and direct-column/whole-row JSON/join probes. These execute real API/SQL/ledger code; authentication is fixture-overridden and the generation test stubs external source building only.
- Node: **10 checks passed**, comprising the 8 paywall-adapter/revalidation/preview tests and the existing auth-return/PWA scripts. Source/generated JavaScript syntax passes. `npm run build:web-assets` and `npm run check:web-assets` pass.
- `compileall`, `pip check`, quota enforcement, schema ownership, migration ledger C1–C7, release policy and `git diff --check` pass. The migration ledger retains 54 recorded applied hashes and separately pins migration 55 as pending; no production application is asserted.
- Browser attempt: the four `report-paywall.spec.js` cases could not launch Chromium because the execution sandbox denied its required socket. No browser assertions executed. Browser/real-device acceptance and live HTTP identity verification remain unverified.
- Independent source review found the additional direct-Supabase bypass and two frontend regressions (stale paid cards and lost free-preview rendering); these were fixed and rechecked. Final independent review reported no remaining blocking finding in the reviewed scope.

Repository test entry points (with a separately configured disposable local database and backend dev dependencies) are `python -m pytest -q --ignore=tests/unit/test_staging_realtime_quota_acceptance.py`, and `node --test tests/unit/report-response-paywall.test.cjs tests/unit/auth-return.test.cjs tests/unit/pwa-reload.test.cjs`. The local aggregate additionally used an execution-only outbound-network guard; it is not application code.

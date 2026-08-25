# AGENTS.md

## Project mission

JPPropDIs ("小象搜房日本" / "ZOU SEEKING HOUSE") turns Japanese property information into reviewable datasets, market summaries, comparison views, and social-media drafts.

The product is still converging on its final architecture. It currently combines an authorized-data CLI, static website, Supabase-backed member experience, FastAPI service, local worker, and model-generated estimates. Do not assume these surfaces share the same trust, ownership, or data-quality guarantees.

## Read this before changing code

1. Read the relevant source file, related SQL or configuration, and any nearby documentation.
2. Trace the complete flow from user input to storage and rendered output. Frontend restrictions are not authorization controls.
3. Identify whether the change affects verified observations, scraped aggregates, modeled estimates, or synthetic fixtures.
4. Surface conflicts between documentation and code instead of choosing one silently.
5. Preserve user changes and generated assets that are outside the task.

## Project map

- `src/jp_property_publisher/`: standardizes authorized CSV records and produces aggregate reports.
- `scripts/`: data collection, content generation, Supabase synchronization, field-option generation, and worker entry points.
- `configs/`: source and presentation configuration for generated reports.
- `data/input/`: manually maintained source data.
- `data/collected/`: collected source snapshots and intermediate records.
- `data/output/`: generated reports and media packages.
- `data/content_library.json`: canonical local content-library copy used by generation scripts.
- `web/`: static member website, analysis UI, copied content library, and generated media.
- `backend/app/`: FastAPI and asyncpg implementation.
- `backend/sql/`: legacy FastAPI schema and Supabase-oriented schema scripts.
- `supabase/functions/jphouse-run/`: authenticated Edge Function that generates or retrieves reports.
- `docs/`: setup, deployment, data dictionary, and content workflow documentation.

## Current data flow

```text
manual CSV or external aggregate page
  -> Python validation/collection scripts
  -> report configuration
  -> content and image generation
  -> data/content_library.json
  -> web/content-library.json and web/library/
  -> optional Supabase synchronization
  -> static website, member workspace, and analysis view

member query
  -> Supabase tables or legacy FastAPI endpoint
  -> generation job
  -> Edge Function, local worker, or FastAPI background task
  -> property report
  -> member workspace and analysis view
```

The Supabase and FastAPI paths are competing implementations, not interchangeable adapters. Do not extend both without an approved consolidation design.

## Data truth and provenance rules

- Every published record must declare one data class: `verified_observation`, `scraped_aggregate`, `modeled_estimate`, or `synthetic_fixture`.
- Never present modeled or synthetic values as collected market facts.
- Never mix listings and closed transactions in one metric unless the output explicitly separates and labels them.
- Store numeric values as numeric fields with units. Do not calculate analytics by parsing presentation strings such as `约3,450万日元`.
- Record source URL, retrieval or verification time, source period, transformation version, and usage-rights status for every non-synthetic dataset.
- Preserve sample size, aggregation method, missing-value policy, and limitations with each statistic.
- `rights_confirmed=yes` is required for the authorized manual-data workflow. A URL alone does not prove permission.
- Do not copy protected listing photos, floor plans, descriptions, agent contact details, or personal information.
- Direct collection from third-party sites requires explicit authorization and a documented review of terms, robots policy, rate limits, retention, and permitted reuse. Do not add stealth, CAPTCHA bypass, proxy rotation, or anti-bot evasion.
- Keep collection fixtures and raw snapshots for parser tests. A parser change must be tested against saved, non-sensitive fixtures before it touches live collection.
- Exchange rates and estimation models must have a dated source or version. Do not hard-code a rate as if it were current.

## Security and privacy boundaries

- Treat the browser, anonymous Supabase client, request bodies, headers, cookies, URLs, third-party responses, webhook payloads, and stored content written by users as untrusted input.
- Enforce authentication, ownership, membership limits, and authorization on the server or with database Row Level Security. UI hiding and email filters are not access controls.
- Scope member-owned rows with an immutable `user_id` tied to `auth.uid()`. Do not use a client-supplied email address as the ownership boundary.
- Anonymous users must not read member names or email addresses, mutate jobs, or update query ownership.
- Do not create broad RLS policies such as `using (true)` or `with check (true)` on tables containing member data or mutable jobs.
- Membership tier and quota fields are server-managed. Users may read them but must not be able to grant themselves a tier or raise a limit.
- Rate-limit signup, login, password reset, query creation, report generation, exports, and notification endpoints. Apply both account and abuse-source limits where appropriate.
- Use Supabase Auth or another server-verified identity provider for production. Do not add localStorage password authentication or unsalted fast password hashes.
- Do not store production access or refresh tokens in new localStorage code. Prefer secure, HttpOnly cookie sessions when the architecture supports them.
- Never commit service-role keys, passwords, private keys, database URLs, or live tokens. A Supabase anon/publishable key may be public only when RLS is correct.
- Redact tokens, email addresses, names, source payloads, and internal exceptions from logs and user-facing errors.
- Confirm before making live database, authentication, RLS, deployment, DNS, billing, or destructive data changes.
- A confirmed authentication bypass, cross-user data access, bulk PII exposure, live secret, or injection path blocks release and must be reported immediately.

## Member and account requirements

- Registration must define email-confirmation behavior, password policy, duplicate-account behavior, and anti-automation controls.
- Provide password reset, logout/revocation, account deletion, and privacy/terms consent before treating the member system as complete.
- Use uniform responses for login, signup, and password reset where account enumeration is possible.
- Require recent authentication for password, email, billing, and security-setting changes.
- Record consent version and timestamp without storing unnecessary personal data.
- Enforce daily query quotas atomically in the database or trusted server path. Displayed limits must match enforced limits.

## Database rules

- PostgreSQL/Supabase is the intended shared datastore. SQLite assumptions do not apply.
- The current `backend/sql/schema.sql` and `backend/sql/supabase_schema.sql` conflict. Treat schema ownership as unresolved until an architecture decision selects one migration history.
- Do not edit an already-applied SQL migration in place. Add a forward migration and use expand/backfill/switch/contract for destructive changes.
- Every table needs a primary key. Relationships, uniqueness, status ranges, month ranges, ownership, and other invariants belong in database constraints.
- Add an index only for a traced query. Consider tenant or owner scope first in composite indexes.
- Claim background jobs atomically. A `select pending` followed by an unrelated `update running` is not safe with multiple workers.
- Use transactions for dependent writes. Perform external side effects after commit or through an outbox/queue design.
- Never run schema initialization on ordinary application startup in production.
- Database changes require a backup/restore plan, rollback or forward-fix plan, and verification query.

## Backend and worker rules

- Prefer one authoritative API and job execution path. Do not add another fallback backend.
- Request handlers coordinate work; long collection, image generation, and report jobs belong in a durable worker or queue.
- Jobs must be idempotent, have bounded retries, record failure classes, and support safe replay.
- Set explicit timeouts and cancellation for outbound requests. Add bounded concurrency, retry only transient failures, and use jittered backoff.
- Do not expose raw exception strings through public job APIs.
- Health checks should distinguish process health from database and dependency readiness.
- Use structured logs with request/job correlation IDs and no PII.

## Frontend and interaction rules

- Keep the public value proposition and primary action visible before account forms, especially at a `390x844` mobile viewport.
- Use one primary action per view. Login and registration may be separate routes or a clearly selected mode, not competing primary buttons.
- Use semantic HTML. Every input needs a visible associated `label`; placeholder text is not a label.
- Preserve visible `:focus-visible` indicators. Never remove `outline` without an equivalent high-contrast replacement.
- Use native buttons, links, dialogs, tables, headings, and form controls before custom ARIA widgets.
- Support keyboard operation, Escape/return focus for dialogs, status announcements, reduced motion, `200%` and `400%` zoom, and touch targets of at least `24x24` CSS pixels with adequate spacing.
- Charts need a textual summary or data table. Canvas pixels and an `aria-label` alone are not an accessible analysis result.
- Escape untrusted content before placing it in HTML. Prefer `textContent` and DOM construction over `innerHTML` when practical.
- Provide loading, empty, error, stale-data, and partial-data states. A slow Supabase request must not indefinitely hide local content or authentication UI.
- Keep generated content, account state, query state, analysis calculations, and API clients in separate modules. Do not continue growing `web/app.js` as a single controller.

## Analytics requirements

- Do not label a single month as a trend. Trend views require multiple periods with comparable definitions.
- Never average unrelated regions merely because they share a month. Group by an explicit geography, asset type, transaction status, and data class.
- Show sample count, period, source class, freshness, unit, aggregation method, and limitations next to every metric.
- Prefer median and distribution bands for skewed property prices; document when an arithmetic mean is appropriate.
- Keep JPY values canonical. Currency conversions must carry rate, source, and effective date.
- Add quality checks for impossible or suspicious values, duplicate records, missing provenance, stale sources, and incompatible dimensions.
- A comparison view must use the same units, period, asset definition, and data class across columns or visibly flag the mismatch.

## Documentation and generated files

- Documentation is part of the product. Run every command you add to a README or runbook.
- Mark generated files and their source. Do not manually edit `web/content-library.json`, generated report folders, or generated images when a script owns them.
- `data/content_library.json` and `web/content-library.json` currently duplicate the same content. Update them through the owning generation/sync workflow and verify their hashes match when both are expected to be identical.
- Keep generated outputs out of architectural decisions. Read source scripts and schemas before judging behavior from generated files.
- Do not add machine-specific absolute paths to shared documentation or commands.
- Update the data dictionary when adding or changing a stored field.

## Local commands

Run commands from the project root unless noted.

Static website preview:

```bash
python3 -m http.server 8787 -d web
```

CLI help without installing the package:

```bash
PYTHONPATH=src python3 -m jp_property_publisher --help
```

CLI development install:

```bash
python3 -m pip install -e .
```

FastAPI development server:

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Basic offline verification:

```bash
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src
node --check web/app.js
python3 -m pip check
```

The repository currently has no automated test, lint, type-check, or CI command. Do not claim those checks passed. Add focused tests with any behavior change and document the command that runs them.

## Verification expectations

- For Python logic, add unit tests for validation, normalization, parsing, calculations, and error paths.
- For SQL/RLS, test anonymous user, owner, another authenticated user, and privileged worker access separately.
- For collection parsers, use stored HTML/JSON fixtures; do not make live websites a required unit-test dependency.
- For frontend changes, test desktop and `390x844` mobile layouts, keyboard navigation, labels, focus, empty/error states, and console errors in a real browser.
- For analytics, use deterministic fixtures with known results and assert units, grouping, sample count, and missing-value behavior.
- For migrations, verify schema state, constraints, RLS policies, affected row counts, and the restore or forward-fix path.
- Before declaring completion, run the relevant commands and report exactly what was and was not verified.

## Change discipline

- Keep changes scoped to the user's request. Do not combine security fixes, schema redesign, visual redesign, and data backfills in one unreviewable patch.
- Prefer small modules and explicit contracts over new frameworks or speculative abstractions.
- Do not add a dependency when the standard library or an existing dependency already solves the problem adequately.
- Never overwrite or delete source data, generated libraries, user changes, or database rows without explicit authorization and a recoverable plan.
- If a required product decision is missing, present the conflict, available options, and consequences before implementation.
- Leave the project in a runnable state and hand off remaining risks explicitly.

## Known release blockers

Treat these as existing risks to resolve, not patterns to copy:

- Anonymous Supabase policies can read and mutate query rows containing member identity fields.
- Query ownership is based on a client-writable email field instead of `auth.uid()`.
- Member tier and daily limits are displayed but not reliably enforced by a trusted backend.
- Verified, scraped, modeled, and synthetic data lack a mandatory shared provenance contract.
- The analysis page derives numbers from display strings and the current content library does not contain a multi-month trend dataset.
- FastAPI, Supabase direct REST, Edge Function, and local worker flows overlap and disagree.
- SQL scripts are used as mutable schema setup rather than a single versioned migration history.
- There are no automated tests, CI gates, restore drills, or production observability standards in the repository.

Do not state that the project is secure, production-ready, or statistically representative until these blockers are remediated and verified.

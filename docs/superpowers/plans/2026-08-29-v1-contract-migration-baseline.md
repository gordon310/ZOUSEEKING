# V1 字段契约与 Supabase Migration Baseline 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已验收的前端界面和报告输出固化为可测试的数据契约，并从空库重建、核对和验证 Supabase migration baseline，为后端 staging 和 V1 业务表提供唯一可回滚入口。

**Architecture:** Supabase Auth 继续作为唯一身份签发方，Supabase PostgreSQL 继续作为当前 V1 数据库，FastAPI 作为私有 API 和授权边界。候选 baseline 先在独立 integration worktree 和本地空库验证；在 schema/RLS/drift/backup 证据齐全并取得单独批准前，不执行 linked `db push`、migration repair、production reset 或 V1 会员/计费/任务 migration。

**Tech Stack:** Supabase CLI、PostgreSQL、SQL migration、FastAPI、Python `pytest`、Playwright、Markdown/JSON 架构文档。

**Spec:** `docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md`、`docs/architecture/adr-0001-authoritative-backend-and-schema.md`、`docs/architecture/authoritative-boundaries.json`

## Global Constraints

- 前端和示例报告已通过产品验收；验收不等于真实支付、会员、额度、任务或报告生成服务验收。
- 每个发布记录必须声明 `verified_observation`、`scraped_aggregate`、`modeled_estimate`、`synthetic_fixture` 或 `user_submitted` 数据类别，并保留来源、时间、版本和限制。
- 当前唯一 active migration history 是 `supabase/migrations/`；`backend/sql/` 只能作为历史 bootstrap/reference，不能作为新 migration 目录。
- 不编辑已应用 migration；需要修复时使用新 migration、expand/backfill/switch/contract 和可回滚的 forward-fix。
- 未完成 baseline reconciliation 前，不添加 V1 membership、billing、task、contact-consent 或 admin 业务表。
- 不执行 linked `supabase db push`、`migration repair`、线上 SQL/RLS/Storage/Auth 写入、production reset 或真实客户数据测试。
- 任何数据库行为验证都必须分别覆盖 anonymous、owner、other authenticated user 和 service worker；UI 隐藏不算授权。

---

### Task 1: 固化已验收的报告与字段契约

**Files:**
- Create: `docs/architecture/v1-report-and-field-contract.md`
- Create: `tests/architecture/test_v1_report_contract.py`
- Modify: `docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: 已验收的 `web/project.html`、`web/data-query.html`、`web/analysis.html`、`web/organization.html`、`web/billing.html`、`web/usage.html`、`web/subscriptions.html`、`web/exports.html`、`web/service-tasks.html` 和 `scripts/create_report_sample_pdf.py`。
- Produces: 一份不依赖 presentation string 的 V1 字段/报告契约，供 migration、FastAPI response model 和 fixture 测试引用。

- [ ] **Step 1: Write the failing contract test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/architecture/v1-report-and-field-contract.md"


def test_v1_contract_declares_core_fields_and_report_states():
    text = CONTRACT.read_text()
    for marker in (
        "asset_type",
        "project_name",
        "data_class",
        "source_url",
        "sample_count",
        "free_preview",
        "full_report",
        "synthetic_fixture",
        "modeled_estimate",
    ):
        assert marker in text


def test_v1_contract_separates_c_and_b_outputs():
    text = CONTRACT.read_text()
    assert "C 端报告" in text
    assert "B 端统计输出" in text
    assert "不能混合挂牌与成交" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/bin/python -m pytest -q tests/architecture/test_v1_report_contract.py`

Expected: FAIL with `FileNotFoundError` because the contract document does not exist.

- [ ] **Step 3: Write the contract document**

The document must define, with units and null policy:

```text
property_id, project_name, project_type, asset_type, purpose,
prefecture, city, ward, address_normalized, address_candidate,
area_sqm, building_year, asking_price_jpy, monthly_cost_jpy,
data_class, source_url, source_period, observed_at, report_version,
sample_count, metric_period_from, metric_period_to, limitation,
report_status, comparable_status
```

It must also list the 11 accepted full-report chapters, the free-preview boundary, B-side statistics fields, the `synthetic_fixture`/`modeled_estimate` display rule, and the rule that missing evidence yields `insufficient_data` rather than an invented conclusion. Do not parse values from strings such as `约3,450万日元`.

- [ ] **Step 4: Run the contract test**

Run: `backend/.venv/bin/python -m pytest -q tests/architecture/test_v1_report_contract.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/architecture/v1-report-and-field-contract.md \
  tests/architecture/test_v1_report_contract.py \
  docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md \
  progress.md
git commit -m "docs: freeze v1 report and field contract"
```

### Task 2: 生成不含客户数据的 staging schema inventory

**Files:**
- Create: `docs/architecture/staging-schema-inventory.md`
- Create: `scripts/inspect_schema_metadata.py`
- Create: `tests/architecture/test_schema_inventory_policy.py`

**Interfaces:**
- Consumes: 只读 `STAGING_DATABASE_URL`、Supabase migration list、`information_schema`/`pg_catalog` 元数据。
- Produces: 表、列、约束、索引、RLS enabled 状态、policy 名称和 migration history 的脱敏快照；不得写入客户行、邮箱、姓名、Storage 对象或 access token。

- [ ] **Step 1: Write the failing inventory policy test**

```python
from pathlib import Path


def test_inventory_document_forbids_member_rows_and_secrets():
    text = Path("docs/architecture/staging-schema-inventory.md").read_text()
    assert "不包含客户行数据" in text
    assert "不包含 access token" in text
    assert "migration_baseline_status" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `backend/.venv/bin/python -m pytest -q tests/architecture/test_schema_inventory_policy.py`

Expected: FAIL because the inventory document does not exist.

- [ ] **Step 3: Implement metadata-only inventory**

The script must refuse to run without an explicitly named database URL environment variable and must execute only metadata queries. The documented read-only commands are:

```bash
supabase migration list --project-ref "$SUPABASE_STAGING_REF"
psql "$STAGING_DATABASE_URL" -v ON_ERROR_STOP=1 -P pager=off \
  -c "select table_schema, table_name, column_name, data_type, is_nullable from information_schema.columns where table_schema in ('public','auth') order by 1,2,ordinal_position"
psql "$STAGING_DATABASE_URL" -v ON_ERROR_STOP=1 -P pager=off \
  -c "select schemaname, tablename, policyname, permissive, roles, cmd from pg_policies where schemaname='public' order by 1,2,3"
```

Record only counts, names, types, constraints, indexes, policies, and migration IDs. If the staging URL or `psql` is unavailable, record `inventory_status=blocked` and do not substitute a guessed schema.

- [ ] **Step 4: Run and review the inventory**

Run: `backend/.venv/bin/python scripts/inspect_schema_metadata.py --database-url-env STAGING_DATABASE_URL --output docs/architecture/staging-schema-inventory.md`

Expected: a deterministic, secret-free document with `migration_baseline_status = reconciliation_required` until the empty-database reset passes.

- [ ] **Step 5: Commit**

```bash
git add scripts/inspect_schema_metadata.py \
  tests/architecture/test_schema_inventory_policy.py \
  docs/architecture/staging-schema-inventory.md
git commit -m "docs: record staging schema metadata inventory"
```

### Task 3: 在隔离 integration worktree 重建 baseline candidate

**Files:**
- Create in the reconciliation worktree: `supabase/migrations/20260824000100_legacy_schema_baseline.sql`
- Create in the reconciliation worktree: `supabase/migrations/20260824000200_foundation_data_contract.sql`
- Create in the reconciliation worktree: `supabase/migrations/20260824000300_private_project_rls.sql`
- Create in the reconciliation worktree: `supabase/migrations/20260824000400_analysis_policy_versions.sql`
- Modify in the reconciliation worktree: `supabase/migrations/README.md`
- Test: `tests/sql/test_foundation_schema.sql`, `tests/sql/test_property_intake_schema.sql`, `tests/security/test_rls_private_projects.sql`

**Interfaces:**
- Consumes: `backend/sql/supabase_schema.sql`、`backend/sql/supabase_user_profiles.sql`、`backend/sql/001_foundation_data_contract.sql`、`backend/sql/002_private_project_rls.sql`、`backend/sql/003_analysis_policy_versions.sql`、现有 `20260825000400`/`20260827000500`/`20260828000100` forward migrations。
- Produces: 从空 Supabase 数据库可按文件名顺序执行、且在现有 intake/photo migrations 之前提供其依赖表的 candidate baseline。

- [ ] **Step 1: Create an isolated worktree from remote main**

```bash
git worktree add -b codex/migration-reconcile \
  /private/tmp/jpp-migration-reconcile origin/main
```

Do not change the current checkout or the live linked project. Keep the candidate branch separate because the current local `main` and remote `main` have different histories.

- [ ] **Step 2: Write the failing fresh-reset assertions**

```bash
cd /private/tmp/jpp-migration-reconcile
supabase start
supabase db reset --local
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" \
  -v ON_ERROR_STOP=1 -f tests/sql/test_foundation_schema.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" \
  -v ON_ERROR_STOP=1 -f tests/sql/test_property_intake_schema.sql
```

Expected before candidate baseline: reset fails at `20260825000400_property_intake.sql` because `public.properties` and `public.residential_details` are missing.

- [ ] **Step 3: Write the minimal ordered candidate migrations**

The first candidate creates the legacy regional tables, `user_profiles`, `query_field_options`, timestamp triggers, required indexes, and safe default grants. The second creates `data_class`, foundation tables, numeric constraints, provenance columns, and indexes. The third adds owner columns, server-managed membership protections, and owner-scoped RLS. The fourth adds policy-version and immutable-metric constraints. All statements must be idempotent where possible, must not backfill ownership from email, and must not copy customer rows.

The old timestamps are intentional for a fresh install but create a known remote-history conflict. Do not run `supabase migration repair`, `supabase db push`, or production reset in this task. Record the conflict and the required backup/forward-fix procedure in `supabase/migrations/README.md`.

- [ ] **Step 4: Run fresh reset and SQL assertions**

Run:

```bash
supabase db reset --local
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 \
  -f tests/sql/test_foundation_schema.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 \
  -f tests/sql/test_property_intake_schema.sql
```

Expected: reset and both assertion files exit 0. If Docker/Supabase local is unavailable, stop this task with `local_reset_status=blocked`; do not claim baseline success.

- [ ] **Step 5: Commit the candidate only after local reset passes**

```bash
git add supabase/migrations supabase/migrations/README.md
git commit -m "feat: reconstruct supabase migration baseline candidate"
```

### Task 4: 完成四类身份的 RLS 行为测试

**Files:**
- Create: `tests/security/test_rls_v1_identity_matrix.sql`
- Modify: `tests/security/test_rls_private_projects.sql`
- Create: `docs/architecture/rls-verification-matrix.md`

**Interfaces:**
- Consumes: candidate baseline 中的 `auth.uid()`、`public.is_service_role()`、owner-scoped policies 和 server-managed triggers。
- Produces: anonymous、owner、other authenticated user、service worker 四种身份的可重复断言。

- [ ] **Step 1: Add the identity matrix assertions**

The SQL fixture must create two disposable Auth users and two owned rows, then assert:

```text
anon: cannot select or mutate member/private query/job/report/property rows
owner: can read own rows; cannot change owner_user_id, membership_tier, daily_query_limit
other authenticated user: receives zero rows and cannot mutate owner rows
service worker: can perform the documented backend writes, but cannot bypass table constraints
```

Use transaction-scoped fixture IDs and roll back the transaction. Do not insert a real email, real customer ID, or production token.

- [ ] **Step 2: Run the four identity classes separately**

Run: `psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/security/test_rls_v1_identity_matrix.sql`

Expected: PASS for all four identities. A failure in any identity blocks the baseline and must be recorded with the policy name and SQLSTATE.

- [ ] **Step 3: Commit**

```bash
git add tests/security/test_rls_v1_identity_matrix.sql \
  tests/security/test_rls_private_projects.sql \
  docs/architecture/rls-verification-matrix.md
git commit -m "test: verify v1 rls identity matrix"
```

### Task 5: 做 schema drift、备份恢复和 forward-fix 演练

**Files:**
- Create: `docs/architecture/migration-reconciliation-report.md`
- Create: `docs/architecture/backup-restore-forward-fix.md`
- Test: `tests/architecture/test_migration_reconciliation_policy.py`

**Interfaces:**
- Consumes: candidate reset output、metadata-only staging inventory、migration list 和 schema-only dump。
- Produces: 不含业务行数据的 drift 对比、恢复步骤、forward-fix 顺序、回滚限制和明确批准点。

- [ ] **Step 1: Write the reconciliation policy test**

```python
from pathlib import Path


def test_reconciliation_report_keeps_live_write_gate_closed_until_all_checks_pass():
    text = Path("docs/architecture/migration-reconciliation-report.md").read_text()
    assert "fresh_reset=pass" in text or "fresh_reset=blocked" in text
    assert "rls_identity_matrix=pass" in text or "rls_identity_matrix=blocked" in text
    assert "live_write_approval=required" in text
    assert "production_reset=forbidden" in text
```

- [ ] **Step 2: Compare metadata and create a schema-only dump**

Run only against disposable/local or explicitly read-only staging credentials:

```bash
supabase db diff --linked --schema public
pg_dump --schema-only --no-owner --no-privileges "$STAGING_DATABASE_URL" \
  > /private/tmp/jpp-staging-schema-only.sql
shasum -a 256 /private/tmp/jpp-staging-schema-only.sql
```

Do not export table data. The report must list missing tables, columns, constraints, indexes, policies, migration IDs, and whether each mismatch is expected historical drift.

- [ ] **Step 3: Document restore and forward-fix**

The runbook must specify: backup artifact, restore target, verification queries, who approves a live change, how to stop after a failed migration, how to apply a corrective forward migration, and why `git revert` does not undo an already-applied SQL migration. Include the old-timestamp baseline conflict and require a backup plus explicit migration-history decision before repair.

- [ ] **Step 4: Commit the reconciliation evidence**

```bash
git add docs/architecture/migration-reconciliation-report.md \
  docs/architecture/backup-restore-forward-fix.md \
  tests/architecture/test_migration_reconciliation_policy.py
git commit -m "docs: define migration reconciliation and restore gate"
```

### Task 6: 集成并部署后端 staging（仅在 Task 1–5 通过后）

**Files:**
- Source: local backend/data commit `57762f5`
- Target: an integration worktree based on the current remote `origin/main`
- Verify: `backend/.venv/bin/python -m pytest -q`, `npm run test:web`, `node --test tests/edge/jphouse-run-authority.test.mjs`

**Interfaces:**
- Consumes: accepted field/report contract、passing baseline/RLS/drift evidence。
- Produces: a fast-forwardable staging release that keeps generated `web/content-library.json` and `web/library/**`, then Render staging health and synthetic smoke evidence.

- [ ] **Step 1: Apply only the backend/data patch onto remote main ancestry**

Use an isolated worktree and path allowlist. Do not push the unrelated local history and do not include `.venv`, `egg-info`, `output/`, `tmp/`, `test-results/`, or secrets.

- [ ] **Step 2: Run the complete offline suite**

Run: `backend/.venv/bin/python -m pytest -q && npm run test:web && node --test tests/edge/jphouse-run-authority.test.mjs`

Expected: all suites pass; any SQL/RLS or browser check that cannot run is recorded as unverified rather than skipped silently.

- [ ] **Step 3: Deploy only to Render staging after explicit deployment approval**

Verify `/health/live`, `/health/ready`, anonymous/owner/other-user behavior, intake/location flows, generated content assets, and log redaction. Do not apply new business migrations or use real customer files.

- [ ] **Step 4: Commit the release evidence**

```bash
git add docs/architecture/migration-reconciliation-report.md progress.md
git commit -m "docs: record v1 backend staging verification"
```

### Task 7: Baseline gate 通过后再拆分 V1 业务 migration

**Files:**
- Create only after the baseline gate: `supabase/migrations/20260830000100_v1_memberships.sql`
- Create only after the baseline gate: `supabase/migrations/20260830000200_v1_usage_ledger.sql`
- Create only after the baseline gate: `supabase/migrations/20260830000300_v1_reports_subscriptions.sql`
- Create only after the baseline gate: `supabase/migrations/20260830000400_v1_task_consent.sql`
- Test: `tests/sql/` and `tests/security/` fixtures for each table and policy

**Interfaces:**
- Consumes: frozen report/field contract and verified authoritative schema.
- Produces: server-managed membership/org roles, atomic usage ledger, report/subscription records, consent-gated task contact exchange, and admin audit records.

- [ ] **Step 1: Do not start until the baseline report records all gates as pass**

Required: `fresh_reset=pass`, `schema_assertions=pass`, `rls_identity_matrix=pass`, `drift_review=pass`, `backup_restore=pass`, and explicit live migration approval.

- [ ] **Step 2: Add one forward migration per bounded domain**

Keep C and B quotas server-managed; reset monthly at UTC+8 month boundary; reject excess without automatic charge; use idempotency keys for report generation and billing webhooks; keep task pricing/settlement outside the platform; require two-sided consent before email exchange.

- [ ] **Step 3: Add tests before each domain migration**

Each domain must cover anonymous, owner, other-user, service-worker, duplicate/retry, failure/no-double-charge, and rollback/forward-fix behavior before staging deployment.

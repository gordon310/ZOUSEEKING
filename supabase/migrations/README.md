# Supabase 前向迁移历史

`supabase/migrations/` 是本项目 Supabase PostgreSQL 的唯一前向迁移历史。

文件级 ownership 审计见 [`docs/architecture/schema-ownership-audit.md`](../../docs/architecture/schema-ownership-audit.md)，机器清单见 [`docs/architecture/schema-ownership.json`](../../docs/architecture/schema-ownership.json)。

## 当前状态

仓库 fresh-install history 已在 disposable local Supabase 通过 reset 和 SQL/RLS
assertions；获批 staging 已通过 later-ID reconciliation 与运行验收：

```text
migration_baseline_status = canonical_staging_reconciled_production_pending
staging_m1_acceptance = pass
future_live_write_approval = required
production_reset = forbidden
```

2026-09-02 仅应用更晚的 `20260902000100`；三条原有 ledger ID 保持不变，
没有伪造或 repair 缺失的历史 ID。完整逻辑备份已恢复到第二套隔离本地
Supabase，恢复后的 ledger/catalog 与迁移前 staging 一致。该结果关闭 M1 staging
门槛，不代表 production 已协调或可发布。

## Canonical history

Fresh install 固定按以下顺序执行：

1. `20260824000100_legacy_schema_baseline.sql`
2. `20260824000200_foundation_data_contract.sql`
3. `20260824000300_private_project_rls.sql`
4. `20260824000400_analysis_policy_versions.sql`
5. `20260824000500_provenance_and_immutable_contract.sql`
6. `20260824000600_provenance_contract_hardening.sql`
7. `20260824000700_user_submitted_source_rights.sql`
8. `20260825000400_property_intake.sql`
9. `20260827000500_legacy_private_data_rls.sql`
10. `20260828000100_property_photo_location.sql`
11. `20260829000100_baseline_access_contract.sql`
12. `20260902000100_staging_baseline_reconciliation.sql`

三条原有且已应用的 migration 保持原字节不变。特别是
`20260828000100` 继续拥有 photo/location/address/project-name fields、constraints
和 owner-scoped indexes。已应用 migration 文件不可修改；任何 remote 修复只能
新增更晚的 forward migration。

本地文件清单变更必须先通过只读审计：

```bash
python3 scripts/check_schema_ownership.py
npm run check:schema-ownership
```

## Final schema decisions

- published reports/metrics/risks 必须带 provenance；非 synthetic 和
  `user_submitted` publication 必须引用 `rights_confirmed` source，且用户提交还要
  有 evidence locator。
- analysis metrics append-only；policy versions 使用 `btree_gist` exclusion
  constraint 防止相同 `policy_key` 的有效期重叠。
- 22 张 application table 启用 RLS。`anon` 只有 active
  `query_field_options` SELECT；authenticated 只有 owner reads 和自己的 profile
  preferences；private writes 通过 FastAPI/service worker。
- 新增 source、metric、period、numeric、location 和 server-managed ownership /
  membership constraints；不从 email 推导 owner，不复制或伪造客户数据。

## Local verification

只在未 linked 的 disposable local worktree 运行：

```bash
supabase db reset --local
supabase db lint --local --level warning
psql "$TEST_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f tests/sql/test_foundation_schema.sql
psql "$TEST_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f tests/sql/test_property_intake_schema.sql
psql "$TEST_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f tests/sql/test_provenance_policy_metric_contract.sql
psql "$TEST_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f tests/security/test_rls_private_projects.sql
psql "$TEST_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f tests/security/test_rls_v1_identity_matrix.sql
psql "$TEST_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f tests/sql/test_m1_reconciliation_contract.sql
```

2026-09-02 上述 reset、lint 与六组 assertions 均通过；lint 返回
`No schema errors found`。staging reconciliation、逻辑备份隔离恢复与 live
四身份/Auth/Storage 验收也通过。详见
`docs/architecture/migration-reconciliation-report.md` 和
`docs/architecture/rls-verification-matrix.md`。

## Live gate and submission rules

- 禁止 migration repair、staging reset、production reset、未经批准的 linked push
  或 live SQL。M1 授权不自动延伸到后续 staging 变更或任何 production 操作。
- 新增 membership、billing、task、contact-consent 或 administrator schema 仍需
  独立设计、迁移审查、备份/恢复和明确批准。
- 新 schema 变更只能新增到本目录；不在应用启动时初始化 schema。
- `backend/sql/`、旧 restore 包和 schema dump 只作为历史证据，不是 migration
  history。
- 每个 migration 必须配套 constraints、focused assertions、backup/restore、
  rollback 或 forward-fix 说明和受控发布步骤。

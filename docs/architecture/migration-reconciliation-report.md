# Supabase migration baseline reconciliation report

## Scope and evidence boundary

本报告记录仓库 migration history、2026-08-30 的只读 staging metadata
inventory、disposable local Supabase，以及 2026-09-02 经明确授权完成的 staging
reconciliation、逻辑备份隔离恢复与运行验收。没有执行 migration repair、
staging/production reset 或任何 production 操作。

staging inventory 来自获准的 Supabase SQL Editor 只读 catalog 查询，记录了
22 张 `public` 表、263 列、97 个约束、72 个索引、20 条 policy、18 个
trigger event、8 个 application function、6 个 extension、5 个 enum label、
315 条所选角色 table grant，以及 3 个 migration ID。该 inventory 不含客户行、
邮箱、姓名、Storage 对象、token、数据库 URL 或 secret。staging 不是 production；
该历史 inventory 和后续 staging 结果都不能证明 production schema、数据或备份状态。

## Gate status

```text
fresh_reset=pass
schema_assertions=pass
rls_identity_matrix=pass
local_restore_drill=pass
staging_transaction_dry_run=pass
canonical_history=selected
retained_photo_address_migration=pass
policy_version_choice=gist_exclusion
staging_inventory=pass
drift_review=pass
blocking_drift=cleared_by_20260902000100
service_role_grant_portability=pass_20260902000200
logical_backup=pass
isolated_restore=pass
backup_restore=pass
forward_fix=pass
staging_rls_auth_storage=pass
provider_physical_backup=not_available_free
future_live_write_approval=required
production_reset=forbidden
migration_baseline_status=canonical_staging_reconciled_production_pending
```

`backup_restore=pass` 是 Supabase Free 可执行的 roles/schema/data/history 完整逻辑
导出与第二套隔离本地 Supabase 恢复，不是付费 physical backup/PITR。M1 授权仅
覆盖命名 staging 和本次 later-ID；任何 future live write 及 production 仍须另行批准。

## Canonical history decision

`supabase/migrations/` 是唯一 canonical forward history。Fresh install 必须按
文件名执行以下 13 个 ID：

| ID | 责任 |
| --- | --- |
| `20260824000100` | legacy regional tables、`user_profiles`、indexes、update triggers、RLS 起点 |
| `20260824000200` | `data_class` 和 properties/evidence/analysis foundation |
| `20260824000300` | immutable owner columns、membership protection、owner RLS 起点 |
| `20260824000400` | policy effective-date 和初始 metric immutability 保护 |
| `20260824000500` | published provenance、metric dimensions、GiST policy exclusion、append-only metrics |
| `20260824000600` | complete source provenance 和 `rights_confirmed` trigger |
| `20260824000700` | user-submitted publication 也必须引用 rights-confirmed source |
| `20260825000400` | accepted property-intake schema |
| `20260827000500` | applied legacy private-data RLS hardening |
| `20260828000100` | applied photo/location/address/project-name fields and indexes |
| `20260829000100` | final canonical RLS、least-privilege grants 和 public field-option exception |
| `20260902000100` | staging baseline reconciliation、complete provenance、constraints 与 final least-privilege access contract |
| `20260902000200` | 显式固定 managed/disposable 环境一致的 `service_role` 表权限 |

三条已经应用且原本存在于当前 history 的文件没有被改写：

| File | SHA-256 |
| --- | --- |
| `20260825000400_property_intake.sql` | `430087f2c10d3e5b9778fe09033667b1903b13b5d44e12418b51d32b20f7c171` |
| `20260827000500_legacy_private_data_rls.sql` | `70aef9978d4673fb5f1a1b438d1b08ef854aca8937011e9af635c0036c09e563` |
| `20260828000100_property_photo_location.sql` | `c14b8c2211806254cbc19c171fe3ce055cebc3a4b053d138243453e1a6917130` |

因此 fresh history 保留了 `analysis_sessions` 和 `properties` 的
`project_name`、坐标、精度、位置来源/时间、`address_candidate`、
`address_source`、`address_precision`，以及 owner-scoped address/name indexes。
不得改写已应用 migration；后续修复只能新增更晚的 forward migration。

## Chosen contracts

### Provenance and constraints

- `data_class` 的唯一值集为 `verified_observation`、`scraped_aggregate`、
  `modeled_estimate`、`synthetic_fixture`、`user_submitted`。
- `sources` 必须保存非空 `source_period`、`observed_at`、
  `transformation_version`、`limitations` 和明确 `permission_status`；不得用
  默认值伪造 rights 状态。
- `free_preview` / `full_report` 的 report、metric、risk 输出必须保存对应
  provenance。非 synthetic 输出必须引用 source；`user_submitted` 还必须有
  evidence locator。
- 非 synthetic 的可发布 source 必须为 `rights_confirmed`，且 output 和 source
  的 `data_class` 必须一致。
- metric 的 `sample_count`、期间、asset type、listing/closed、aggregation 和
  limitation 均由 constraint 校验；analysis metrics 为 append-only，新版本写
  新 row，不允许 UPDATE/DELETE 覆盖历史。
- 金额和面积保持 `numeric`；月份、非负金额/费用、年份、位置范围和 intake
  expiry 等 invariants 在数据库 constraint 中执行。

### RLS and privileges

- 22 张 application table 均启用 RLS；intake/private server tables 对
  `anon`/`authenticated` 无直接 policy。
- `anon` 只有 `query_field_options` 的 `SELECT`，policy 只返回
  `is_active=true`；没有 INSERT/UPDATE/DELETE。
- `authenticated` 只有 owner-scoped private reads 和自己的 profile
  preference INSERT/UPDATE；不得直接写 property/query/job/report，不得改
  `owner_user_id`、`membership_tier` 或 `daily_query_limit`。
- service worker 使用 local/managed `service_role` 的 trusted path；它仍受
  PK/FK/UNIQUE/CHECK、source-rights、policy-version 和 append-only constraints。
- final owner policies 使用 `(select auth.uid())`，并为 owner/RLS lookup 保留
  或新增对应索引。

### Policy versions

最终选择 `btree_gist` + `policy_documents_no_overlapping_versions` exclusion
constraint。它按 `policy_key` 排斥相交 `daterange`，`effective_to=NULL` 表示无界
上限；相邻的不重叠区间可插入，重叠区间返回 exclusion violation。旧的
`prevent_policy_version_overlap()` trigger 在最终 schema 中被移除。选择
exclusion constraint 的原因是数据库可以在并发写入时执行冲突检测，而
trigger 的 `EXISTS` check 存在 check-then-write race。

## Fresh local evidence (2026-08-30)

- Supabase CLI `2.116.0`、Docker `29.7.2`、PostgreSQL client `18.6`。
- 原始三文件 history 的 RED reset 在 `20260825000400` 以
  `missing prerequisite table: public.properties` 失败。
- 完整 11-file history 的 `supabase db reset --local` exit 0，并按上表顺序
  应用全部 migration。
- `supabase db lint --local --level warning` exit 0，返回
  `No schema errors found`。
- 以下 assertion files 在 fresh database 上全部 exit 0：
  `tests/sql/test_foundation_schema.sql`、
  `tests/sql/test_property_intake_schema.sql`、
  `tests/sql/test_provenance_policy_metric_contract.sql`、
  `tests/security/test_rls_private_projects.sql`、
  `tests/security/test_rls_v1_identity_matrix.sql`。
- local canonical catalog：22 tables、300 columns、116 `pg_constraint` rows、
  75 indexes、16 policies、24 trigger-event rows、9 application functions、
  7 extensions、5 enum labels、170 selected-role grants、11 migration IDs。
- local selected-role grants：`anon=1`、`authenticated=15`、
  `service_role=154`。
- local schema-only artifact（不含 owner/ACL，不能用于恢复）SHA-256：
  `88c917b280b8b864163b6f964083f5a48eac10649d857a51f52c5c41f5069dbf`。
- local custom-format full dump SHA-256：
  `5fa2e2b434f11788d939a2c9aa0961bdf2c30704a9c5febef760de3c26280503`。
  它恢复到新建的 `jpp_canonical_restore_de60` disposable database；五个
  assertion files 在修正一个 search-path-sensitive 静态断言后全部通过，随后
  restore target 被删除。两个 artifact 只保存在 `/private/tmp`，没有提交。

## Staging-to-canonical drift

| Object class | Staging | Canonical local | Classification |
| --- | ---: | ---: | --- |
| tables | 22 | 22 | table names match |
| columns | 263 | 300 | blocking: canonical adds 37 provenance/publication columns |
| constraints | 97 | 116 | blocking: provenance, publication, metric and policy exclusion differences |
| indexes | 72 | 75 | expected/blocking: GiST exclusion and two RLS lookup indexes |
| policies | 20 | 16 | expected tightening: remove direct property writes and service policy; keep active field options |
| trigger events | 18 | 24 | blocking: source-rights enforcement is not on staging |
| application functions | 8 | 9 | blocking: source-rights function and policy mechanism differ |
| extensions | 6 | 7 | canonical adds `btree_gist` |
| enum labels | 5 | 5 | match |
| selected-role grants | 315 | 170 | blocking least-privilege drift; not proof of an existing RLS bypass |
| migration IDs | 3 | 11 | blocking history drift |

canonical local now包含 staging inventory 中的 photo/location/address 列和索引；
它额外加入完整 provenance contract。staging 仍只有 `20260825000400`、
`20260827000500`、`20260828000100`，缺少七个旧 baseline ID 和最终 access ID。
不得用 timestamp 重命名、`supabase migration repair`、linked
`supabase db push` 或 reset 强行制造一致。

## 2026-08-31 staging migration dry-run

- `supabase db push --dry-run --project-ref fnogxuytbabxmqousifh` 只读返回
  `Found local migration files to be inserted before the last migration on remote database`，未执行写入。
- 只读重跑 `supabase db push --dry-run --include-all --project-ref fnogxuytbabxmqousifh`
  返回 `upToDate=false`，列出将要推送的 8 个文件：
  `20260824000100`–`20260824000700` 以及 `20260829000100`。远端已有的
  `20260825000400`、`20260827000500`、`20260828000100` 未被列入。
- 该 dry-run 不构成 apply 批准；本轮没有执行 migration、repair、reset 或数据写入。
  不得用 `--include-all` 绕过历史顺序；必须先取得 provider backup、隔离恢复和
  existing-row provenance 分类，再设计审核后的 later-ID reconciliation migration。

## Pre-M1 live blockers（2026-09-02 已闭合）

1. 已通过 CLI 生成 staging roles/schema/data/history 逻辑备份，并校验 SHA-256。
2. 已在第二套隔离本地 Supabase 单 transaction 恢复；ledger/catalog 与迁移前
   staging 一致。Free 没有 physical backup/PITR，明确记为不可用而非 PASS。
3. staging Auth users、22 张业务表和 Storage objects 均为 0；migration preflight
   也会在发现无法安全分类的既有数据时 fail closed，没有伪造 provenance。
4. 新增并审核晚于全部既有 ID 的 `20260902000100`；没有把七条早期 ID 补写进
   remote ledger，也没有执行 repair。
5. exact staging target 与本次 live write 已获用户明确授权；transaction dry-run、
   backup/restore 和 stop conditions 均先于正式 push 完成。

## 2026-08-31 本轮 disposable 执行证据

- 在本机 disposable Supabase 项目执行 `supabase db reset --local --yes`，exit 0；11 个 migration ID 均按 canonical 顺序应用。
- 只读 ledger 核对为 11 条：`20260824000100`–`20260824000700`、`20260825000400`、`20260827000500`、`20260828000100`、`20260829000100`。
- `supabase db lint --local --level warning` exit 0，返回 `No schema errors found`。
- fresh-reset 数据库上的五组 assertions 全部 exit 0：foundation、property-intake、provenance/metric、private-project RLS、V1 identity matrix。
- local catalog 计数复核：22 public tables、300 columns、116 constraints、75 indexes、16 policies、7 extensions。
- custom-format dump checksum：`b9e521827d32647157cf1676bf53a2e9e0e2fd4149bba189fd6f886b466dc215`；恢复到新建 disposable 数据库后，五组 assertions 全部 exit 0。
- dump/restore artifact 与恢复目标均为本机 disposable 资源，不含客户行，不进入 Git；未执行 linked push、repair、staging reset、production 操作或部署。

## 2026-08-31 staging provider 预检证据

- `supabase backups list --project-ref fnogxuytbabxmqousifh` 返回 `walg_enabled=true`、`pitr_enabled=false`、`backups=[]`；没有 provider physical backup 可供隔离恢复。
- `supabase storage ls` 只发现 `property-intake/` bucket；递归 object count 为 `0`，未读取或复制对象内容。
- 费用上限 `JPY 0`，未启用 PITR、clone、临时 compute、retention 或其他可能收费的 provider 配置。
- 因 provider backup 缺失，`backup_restore=blocked`、`forward_fix=blocked` 和 live reconciliation blocker 保持不变。

以上小节是 2026-08-31 的历史预检快照；其 blocker 已由下面的零费用逻辑恢复
路径和 later-ID reconciliation 在 2026-09-02 关闭，不应再作为当前 staging 状态。

## 2026-09-02 M1 staging reconciliation 证据

### Dry-run、备份与恢复

- 在 staging transaction 中执行 `20260902000100`、临时 ledger 记录和 M1 SQL
  assertion 后回滚，结果为 `M1_STAGING_TRANSACTION_DRY_RUN_PASS`；回滚后新 ledger
  ID 和新 provenance column 均不存在。
- pre-change logical backup 包含 roles、public schema/data 和 migration-history
  schema/data。五个 artifact 总计 `106656` bytes，SHA-256 分别为：
  - roles: `168a95a9c745af5ed4679751f90419ac9dc434240a213b03e32a06d5664c2308`
  - schema: `6797a79aab074079fae62ce6d16015e821837082f88d036782c24db10a7bab8f`
  - data: `95017a0139c52ebe9a4fd9d43c649b7c121afc76bcf62e6d535defe7c9786c8b`
  - history schema: `18b99fbbb3ec9fbb964bb255a56171329acd99b6977ece2addd89fdf5aa5105b`
  - history data: `ab1c249b02b0452d0183f20998f0e7925ada6e84ef2d49e6a04447ed364de8cc`
- 在第二套隔离本地 Supabase 中以 provider-compatible admin role 单 transaction
  恢复成功。恢复结果与 pre-change staging 一致：22 tables、263 columns、72
  indexes、20 policies、三条原 ledger ID、0 Auth users、0 业务行和 0 Storage
  objects。artifact 与隔离 target 都不进入 Git。

### Later-ID apply 与最终库存

- 首次 linked push dry-run 只列出
  `20260902000100_staging_baseline_reconciliation.sql`；正式 push 也只应用这一条。
  migration SHA-256 为
  `77c229259060bee1c6b9dde94224adc7bfa65cf7e550a1e627687a0f20c756cd`。
- GitHub CI 使用的 Supabase CLI `2.115.0` 暴露了 disposable stack 未自动
  赋予完整 `service_role` 表权限的版本差异。因 `20260902000100` 已应用，
  未改写旧文件，而是新增
  `20260902000200_service_role_grant_portability.sql`。它的 linked dry-run 与
  push 都只包含这一条，SHA-256 为
  `d6872949b94b47488fa8c39e1f6328ac9b25af7fb13e6a2ce1564adcf7206bb0`。
- 最终 staging ledger 为 `20260825000400`、`20260827000500`、
  `20260828000100`、`20260902000100`、`20260902000200`。未执行 migration
  repair，未修改任何已应用 migration 文件，未伪造早期 ID。
- 最终 catalog 为 22 tables、300 columns、75 indexes、16 policies、0 张 RLS
  disabled application table、170 selected-role grants；M1 contract assertion 返回
  `M1_STAGING_RECONCILIATION_PASS`。
- post-fix 实时 schema dump 包含 22/22 条 application table
  `GRANT ALL ... TO service_role`，dump SHA-256 为
  `bc13f99606b1def793d3c513a2063661031b19f1965722128be31e0b401f5bce`。
- 最终 local fresh reset 重放 13 条 canonical migration，六组 SQL/RLS
  assertions 全部通过；database lint 返回 `No schema errors found`。

### 行为验收与清理

- 数据库匿名/本人/他人/worker 四身份矩阵为 `PASS`：匿名只读 active field
  options，本人只读自身业务记录并只改 profile preferences，他人记录不可见，
  worker 可受信写入但仍受数据库 constraints。
- 私有 Storage 四身份矩阵为 `PASS`：匿名、本人和他人均不能直接访问；worker
  完成 upload/download/delete/restore/delete，恢复前后内容 hash 一致。当前架构
  故意采用 service-only Storage，owner denial 是契约，不是缺陷。
- Auth 生命周期为 `PASS`：email confirmation required、未确认登录拒绝、token
  verify、确认后登录、重复注册不泄露既有 user ID、密码恢复、refresh rotation、
  global logout/revocation、Admin hard delete 与 profile cascade。
- 公开 `/recover` 的真实邮件投递为 `NOT_EXECUTED`，因为没有专用 SMTP sink；
  使用 Admin recovery token 的密码重置行为已通过。access JWT 在自身到期前仍可能
  有效，验收不把它误写为立即失效。
- 清理为 `PASS`：最终 Auth users、public 业务行、Storage objects 和 synthetic
  Storage objects 均为 0。
- `20260902000200` 应用后重跑完整行为验收，四身份、Auth、Storage 和
  fixture cleanup 再次全部 `PASS`。

## Remaining production blockers

- production database/Auth/Storage 未连接、未修改、未验证；production deploy、
  DNS、billing 和真实用户/文件也为 `NOT_EXECUTED`。
- Free staging 没有 provider physical backup/PITR。M1 用官方支持的逻辑导出和
  隔离恢复关闭 staging 恢复门槛；首次接收不可丢失数据前仍需选择 production
  RPO/RTO、数据库备份与独立 Storage object backup 策略。
- 正式恢复邮件投递需要专用 SMTP、模板/redirect allowlist、频率与送达性验收。
- 任一后续 migration 都需要新的 reviewed later-ID、备份/恢复、明确 target 和
  live-write approval；M1 授权不能复用。

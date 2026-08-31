# Supabase migration baseline reconciliation report

## Scope and evidence boundary

本报告只核对仓库 migration history、2026-08-30 的只读 staging metadata
inventory，以及 disposable local Supabase PostgreSQL。它没有执行 linked
`supabase db push`、`supabase migration repair`、staging reset、staging
SQL/RLS/Auth/Storage 写入或任何 production reset／production 操作。

staging inventory 来自获准的 Supabase SQL Editor 只读 catalog 查询，记录了
22 张 `public` 表、263 列、97 个约束、72 个索引、20 条 policy、18 个
trigger event、8 个 application function、6 个 extension、5 个 enum label、
315 条所选角色 table grant，以及 3 个 migration ID。该 inventory 不含客户行、
邮箱、姓名、Storage 对象、token、数据库 URL 或 secret。staging 不是 production；
该 inventory 不能证明 production schema、数据或备份状态。

## Gate status

```text
fresh_reset=pass
schema_assertions=pass
rls_identity_matrix=pass
local_restore_drill=pass
canonical_history=selected
retained_photo_address_migration=pass
policy_version_choice=gist_exclusion
staging_inventory=pass
drift_review=pass
blocking_drift=present
schema_only_dump=blocked
forward_fix=blocked
backup_restore=blocked
live_write_approval=required
production_reset=forbidden
migration_baseline_status=canonical_local_pass_live_reconciliation_required
```

`fresh_reset=pass` 只表示仓库选择的单一 history 可以从空的 local Supabase
重建。`drift_review=pass` 只表示 inventory 中的差异已分类，不表示 staging
与 local 相同。`backup_restore=blocked` 指 provider-supported staging backup
及 isolated staging-clone restore 尚未完成；它与 `local_restore_drill=pass`
不矛盾。任何 local PASS 都不授权 live write。

## Canonical history decision

`supabase/migrations/` 是唯一 canonical forward history。Fresh install 必须按
文件名执行以下 11 个 ID：

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

## Remaining live blockers

1. 没有 direct staging database URL，因此没有 staging schema-only dump；现有
   SQL Editor inventory 不能替代 dump。
2. 没有 provider-supported encrypted staging backup，也没有 isolated staging
   clone restore drill，因此 `backup_restore=blocked`。
3. 需要在 restored staging clone 上审计 existing rows，确认哪些 provenance
   可由证据回填；缺失事实不得编造，旧 published rows 不能静默通过新约束。
4. 需要新增 ID 晚于 `20260829000100` 的 expand/backfill/validate forward
   migration，并在 clone 上验证。旧 `20260824000100–00700` 只定义 fresh
   history，不能直接补写 staging ledger。
5. database owner 与 release owner 仍须批准 exact target、backup identifier /
   checksum、forward migration IDs、restore result、maintenance window 和 stop /
   forward-fix owner。

在以上 blocker 解决前，禁止 linked push、migration repair、staging reset、
production reset 和 V1 membership/billing/task/contact-consent/admin migration。

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

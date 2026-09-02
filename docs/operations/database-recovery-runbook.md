# Provider backup、隔离恢复与 migration forward-fix runbook

## 当前门槛

```text
local_archive_checksum_and_toc=pass
candidate_local_restore=pass
current_canonical_restore_acceptance=pass
staging_logical_backup=pass
staging_isolated_logical_restore=pass
staging_storage_object_restore=pass_synthetic
provider_physical_backup=not_available_free
migration_forward_fix=pass_20260902000100_and_20260902000200_staging_only
production_restore=not_authorized
migration_baseline_status=canonical_staging_reconciled_production_pending
```

本 runbook 记录离线工具、验收标准，以及 2026-09-02 已获授权的 staging M1
执行证据；它不授权未来线上变更。`production reset` 始终禁止；production restore
必须另立事故恢复决策并获得明确批准。

2026-08-31 本机 local-only drill 已通过；2026-09-02 又完成 staging Free 逻辑
备份、隔离恢复、later-ID reconciliation 和 synthetic Storage object 恢复。
physical backup/PITR 仍不可用，production 状态不变。

## 前期零成本模式（2026-08-31 已确认）

- 项目尚未上线，费用上限为 `JPY 0`，当前不创建 Render 付费 PostgreSQL，也不启用 Supabase PITR、Restore to a new project 或临时 compute。
- 前期数据库/Auth/Storage 继续使用 Supabase Free；该计划包含 500 MB database quota、1 GB Storage 和 5 GB egress，但没有 automatic database backup/PITR，低活跃项目可能在一周后暂停。[Supabase Pricing](https://supabase.com/pricing) · [Database Backups](https://supabase.com/docs/guides/platform/backups) · [Project Pausing](https://supabase.com/docs/guides/platform/free-project-pausing)
- 获明确授权时，可按 Supabase 官方 CLI 流程导出 roles/schema/data 并在隔离
  target 恢复；artifact 必须受限保存、校验 checksum，并且不进入 Git。
- 首次接收真实用户或不可丢失数据前，必须依据 RPO/RTO 选择可持续的 production
  备份方案（定期逻辑备份或付费 physical/PITR）、独立 Storage object backup、
  隔离恢复和费用/保留审批。M1 Free staging 证据不能作为 production release pass。

Render paid Postgres 的 PITR/恢复能力不能抵消当前架构迁移成本：本项目现有 migration、Supabase Auth（`auth.users`/`auth.uid()`）和 private Storage 仍以 Supabase 为边界。若以后迁移到 Render，必须另立架构决策、重建 migration baseline 并重新验收 Auth/RLS/Storage。

## 2026-08-31 staging provider 预检

本节是 M1 前的历史快照；当前结果见下一节。

- 目标：Supabase staging `zoubeacon-staging`（ref `fnogxuytbabxmqousifh`）。
- `supabase backups list`：`walg_enabled=true`、`pitr_enabled=false`、`backups=[]`；没有可引用的 provider physical backup。
- Storage bucket 列表只有 `property-intake/`；递归对象计数为 `0`，没有对象需要复制或恢复。
- 没有启用 PITR、创建 clone、执行 provider restore、读取 Storage 对象内容或写入远端资源。
- 费用上限为 `JPY 0`，因此不启用可能收费的 PITR、Restore to a new project、临时 compute 或 retention 变更。
- 结论：`provider_backup` 与 `isolated_provider_restore` 继续 blocked；须提供现有 provider backup/restore 证据，或另行批准费用后再继续。

## 2026-09-02 M1 Free 逻辑备份与隔离恢复

- 迁移前导出 staging roles、public schema/data 和 migration-history schema/data；
  五个 artifact 共 `106656` bytes，均记录并复核 SHA-256，没有提交到 Git。
- 第二套隔离本地 Supabase 以匹配 provider 权限的 admin role 在单 transaction 中
  恢复成功。恢复结果为 22 tables、263 columns、72 indexes、20 policies、三条
  原 ledger ID、0 Auth users、0 public rows 和 0 Storage objects，与源 inventory
  一致。
- 数据库备份不包含 Storage blob。因为源 bucket 对象数为 0，另以 synthetic
  fixture 验证 worker upload/download/delete/restore/delete，内容 hash 一致且最终
  object count 回到 0；这不是 production 对象备份证据。
- 逻辑恢复满足 M1 staging 的零费用恢复验收。Supabase Free 的 physical backup /
  PITR 仍记为 `not_available_free`，没有启用付费功能。

2026-08-30 本地审阅确认现有 custom-format artifact `jpp-local-baseline-full-94644b6.dump` 的大小为 `545277` bytes，SHA-256 为 `4c7c555a543c9a89c009ba7cc99cf31d2442847d553de5ba586c56a4da612b3d`，源 PostgreSQL 为 `17.6`，生成工具为 `pg_dump 18.6`，TOC 有 `1067` 个条目和 `70` 个 `TABLE DATA` 条目。检查只读取 artifact bytes 和 `pg_restore --list` TOC，没有导出或查看表行。

该 artifact 在无持久卷的本地 PostgreSQL 17.6 disposable target 上完成 owner/ACL-preserving restore，并通过其所属 candidate commit `2af3b2c` 的 5 个 foundation、intake、provenance、private-RLS 和身份矩阵断言；目标随后删除。用当前 worktree 的断言复测时，foundation 通过，intake 因 artifact 不含 `20260828000100` 的 location/address 字段而失败，后续 private-RLS 断言按停止规则标为 `not_run`，目标仍成功删除。这是 blocking drift，不得把 candidate pass 当作当前 main、staging 或 production 的恢复证据。

## 负责人和批准记录

每次 provider backup、隔离恢复、migration 或 forward-fix 都必须在受限 release/incident record 中分配以下负责人。记录团队或人员标识与审批单号，不记录邮箱、密码、token、database URL 或私钥。

| 字段 | 责任 |
| --- | --- |
| `database_owner` | 确认源与目标环境、PostgreSQL 版本、backup 类型、migration ledger 和数据库停止条件。 |
| `backup_operator` | 选择或创建已批准的 provider backup，记录不可变 ID、恢复点、保留策略和完整性证据。 |
| `recovery_lead` | 建立隔离目标、执行恢复、运行验收、隔离副作用并负责目标处置。 |
| `release_owner` | 批准精确 migration ID、维护窗口、应用顺序和放行结果。 |
| `forward_fix_owner` | 负责失败分类、新的更晚 migration、断言和再次演练。 |
| `incident_commander` | migration 失败后冻结后续动作，维护时间线并协调升级。 |
| `security_reviewer` | 复核 clone 的 Auth/RLS、网络限制、日志脱敏和凭证边界。 |
| `billing_owner` | 批准 PITR add-on、Restore to a new project、临时 compute 和 clone 保留产生的费用。 |

模板位于 [`database-recovery-evidence.template.json`](database-recovery-evidence.template.json)。原始模板的 `gate_status=blocked` 且负责人为空，必须校验失败；它不能作为放行证据。完成后的记录放在受限 release/incident 系统，不要提交包含项目 ID、人员信息或恢复作业 ID 的 live record。

## 2 种完整性模式

不要为 provider-managed physical backup 伪造 checksum。

| Backup 类型 | `checksum_mode` | 必需证据 |
| --- | --- | --- |
| 可下载 logical/custom artifact | `sha256` | artifact 名称、bytes、SHA-256、`checksum_verified=true`、`pg_restore --list`、PostgreSQL/pg_dump 版本。 |
| Supabase physical backup 或 PITR | `provider_managed_identifier` | provider backup ID 或恢复时间点、provider restore job ID、`sha256=null`、`checksum_verified=false`、成功的隔离恢复和 catalog/assertion 结果。 |

Supabase 当前文档说明 physical backup 可能不可下载；这种情况下，provider backup/job ID 与成功恢复是完整性链的一部分，不能用 schema-only dump 代替。参考 [Database Backups](https://supabase.com/docs/guides/platform/backups) 和 [Restore to a new project](https://supabase.com/docs/guides/platform/clone-project)。

## Provider backup 预检和停止条件

以下任一项不满足时，停止，不得进入 migration：

- `database_owner`、`backup_operator`、`recovery_lead`、`release_owner`、`forward_fix_owner` 和 `incident_commander` 未分配；
- source environment、精确 project record、PostgreSQL version 或 migration ledger 未确认；
- 没有 migration 前的 provider backup ID/恢复点，或 backup 已超出保留期；
- backup 类型、加密、保留负责人、访问路径或隔离 restore target 未记录；
- 使用 Restore to a new project、PITR add-on 或临时 compute，但没有 `billing_owner` 批准；
- 没有独立 Storage object backup/restore 记录；
- 没有同一 backup 的隔离恢复和验收结果；
- canonical migration history、当前 blocking drift 或 forward-fix owner 尚未决定；
- 请求包含 `supabase migration repair`、修改已应用 migration、linked reset、production reset 或无审查的原地 restore。

Supabase 的数据库 backup 只包含 Storage 元数据，不包含 Storage API 中的对象；恢复数据库不会恢复已删除的文件。Storage object 的备份、checksum、权限和恢复演练是独立 release blocker，不能在数据库验收中标记为通过。[Database Backups](https://supabase.com/docs/guides/platform/backups) 明确记录了这一边界。

## 获得 live 和 billing 批准后的 provider 流程

本节由指定 operator 执行；本次没有执行。

1. `backup_operator` 在 Supabase Dashboard 的 **Database > Backups** 中记录 migration 前最近一个可用 daily physical backup 或 PITR 恢复点。记录 backup ID、UTC 时间、保留窗口、PostgreSQL version、source environment 和 provider 页面状态。
2. 如果项目没有满足 RPO 的 provider backup，停止。启用 PITR、升级 compute 或改变 retention 会产生 billing 和 live configuration 变更，必须先取得新的批准。
3. 不用 production/staging 原地 restore 做演练。优先使用 Supabase **Restore to a new project** 创建数据库隔离 clone；该功能会复制数据库 schema、数据、roles、permissions、Auth users 和 encryption root key，也会产生独立项目费用。[Restore to a new project](https://supabase.com/docs/guides/platform/clone-project) 记录了复制范围和费用边界。
4. 新 clone 不接入应用环境变量、worker、webhook、邮件、DNS、CI 或公开客户端。确认网络限制和 SSL 设置，检查 `pg_cron`、`pg_net`、wrappers 与其他可产生外部副作用的扩展；存在活动副作用时停止，由 `recovery_lead` 提交隔离变更审批后处理。Supabase 官方文档同样要求 clone 后禁用可能执行外部操作的扩展。
5. 记录 provider restore job ID、clone project record、region、开始/结束 UTC、PostgreSQL version 和所有非数据库组件缺口。Auth settings/API keys、Storage objects/settings、Edge Functions、Realtime settings 和 read replicas 不由数据库 clone 自动完成，必须分别验收。
6. 仅运行下面的 metadata catalog 检查和与该 backup commit 完全一致的 SQL assertions。不要查询、抽样或导出客户行。身份矩阵使用固定测试 UUID 并在 transaction 中回滚，不使用真实会员或房产。
7. `security_reviewer` 对 anonymous、owner、other authenticated user 和 service worker 分别验收 RLS/grants；`database_owner` 对 migration ledger、constraints、indexes、policies 和 extensions 验收；`release_owner` 复核所有 stop condition。
8. clone 的保留或删除是 billing 和破坏性操作。`recovery_lead` 记录处置时间与审批，不能由本 runbook 自动删除 provider project。

如果 provider physical restore 不可用，Supabase 提供 logical backup/restore 流程，
分别导出 roles、schema 和 data；这会读取和导出数据库内容，只能由获批 operator
在加密受限位置执行。M1 staging 已在空业务数据前提下运行并完成隔离恢复；未来
重复执行前仍需重新核对 [Backup and Restore using the CLI](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore)，因为 provider 命令和限制会变化。

## Metadata-only restore 验收

以下 SQL 只读取 catalog 和 migration ledger，不读取业务表行：

```sql
select version
from supabase_migrations.schema_migrations
order by version;

select table_name, column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
order by table_name, ordinal_position;

select tc.table_name, tc.constraint_name, tc.constraint_type
from information_schema.table_constraints tc
where tc.table_schema = 'public'
order by tc.table_name, tc.constraint_name;

select schemaname, tablename, indexname
from pg_indexes
where schemaname = 'public'
order by tablename, indexname;

select n.nspname, c.relname, c.relrowsecurity
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind in ('r', 'p')
order by c.relname;

select schemaname, tablename, policyname, permissive, roles, cmd
from pg_policies
where schemaname = 'public'
order by tablename, policyname;

select table_name, grantee, privilege_type, is_grantable
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('anon', 'authenticated', 'service_role')
order by table_name, grantee, privilege_type;

select t.typname, e.enumlabel, e.enumsortorder
from pg_type t
join pg_namespace n on n.oid = t.typnamespace
join pg_enum e on e.enumtypid = t.oid
where n.nspname = 'public'
order by t.typname, e.enumsortorder;
```

验收记录必须比较 source inventory、backup commit expectation 和 restored target。缺失对象、额外高权限 grant、RLS 关闭、policy 不一致、migration ID 不一致、扩展/role 不兼容或断言失败均为 stop condition，不得解释为“基本通过”。

## 本地 custom-format disposable drill

[`scripts/database_recovery.py`](../../scripts/database_recovery.py) 只接受 loopback host、maintenance database `postgres` 和 `jpp_restore_` 前缀目标。它先校验 SHA-256 和 `PGDMP`/TOC，再创建新数据库，执行 owner/ACL-preserving `pg_restore`，按参数顺序运行 assertion；首个失败后将剩余 assertion 标记为 `not_run`。只有工具成功创建的目标才会执行 `dropdb`，报告不保存 database URL、密码或原始 stderr。

所需变量必须由受限本地 shell 提供：

```text
JPP_RECOVERY_ARTIFACT
JPP_RECOVERY_SHA256
JPP_LOCAL_RECOVERY_DATABASE_URL
JPP_RECOVERY_REPORT
JPP_BACKUP_IDENTIFIER
JPP_DATABASE_OWNER
JPP_BACKUP_OPERATOR
JPP_RECOVERY_LEAD
JPP_RELEASE_OWNER
JPP_FORWARD_FIX_OWNER
JPP_INCIDENT_COMMANDER
```

先做不连接数据库的 artifact 检查：

```bash
python3 scripts/database_recovery.py inspect \
  --artifact "$JPP_RECOVERY_ARTIFACT" \
  --expected-sha256 "$JPP_RECOVERY_SHA256"
```

再对一次性本地目标执行恢复。`JPP_LOCAL_RECOVERY_DATABASE_URL` 必须指向 loopback 的 `postgres` maintenance database；不要把 provider/staging/production URL 放入该变量。

```bash
python3 scripts/database_recovery.py drill \
  --artifact "$JPP_RECOVERY_ARTIFACT" \
  --expected-sha256 "$JPP_RECOVERY_SHA256" \
  --database-url-env JPP_LOCAL_RECOVERY_DATABASE_URL \
  --target-database jpp_restore_release_candidate \
  --assertion tests/sql/test_foundation_schema.sql \
  --assertion tests/sql/test_property_intake_schema.sql \
  --assertion tests/security/test_rls_private_projects.sql \
  --backup-identifier "$JPP_BACKUP_IDENTIFIER" \
  --report "$JPP_RECOVERY_REPORT" \
  --database-owner "$JPP_DATABASE_OWNER" \
  --backup-operator "$JPP_BACKUP_OPERATOR" \
  --recovery-lead "$JPP_RECOVERY_LEAD" \
  --release-owner "$JPP_RELEASE_OWNER" \
  --forward-fix-owner "$JPP_FORWARD_FIX_OWNER" \
  --incident-commander "$JPP_INCIDENT_COMMANDER"

python3 scripts/database_recovery.py validate-record "$JPP_RECOVERY_REPORT"
```

完整 Supabase dump 需要目标 cluster 已存在匹配的 provider roles。缺失 role 或 restore operator 无法 `SET ROLE` 时停止；不要通过 `--no-owner` 或 `--no-privileges` 把 recoverable backup 降级为只适合 schema comparison 的 artifact。

## Checksum 和 restore 验收清单

每项必须为 `pass` 或明确 `not_applicable_provider_managed`；不得留空。

- Backup ID/恢复点属于正确 source environment，创建时间早于 migration window，仍在 retention 内。
- Logical/custom artifact 的实际 SHA-256 等于受限 release record；provider-managed physical/PITR 明确记录 `sha256=null` 和 provider backup/job ID。
- `pg_restore --list` 成功，archive format、bytes、源 PostgreSQL 和 pg_dump version 已记录；没有用 `--no-owner`/`--no-privileges` 降级恢复证据。
- Restore target 是新建 disposable local database 或隔离 provider clone，不是 source database。
- Restore operator 可恢复 owners、ACL、roles 和 extensions；任何忽略错误的参数都会导致失败。
- Migration ledger 与批准的精确 ID 顺序一致。
- Tables、columns、constraints、indexes、RLS、policies、selected-role grants 和 enums 的 catalog 结果一致；blocking drift 为 0。
- Foundation、intake、provenance、private-RLS 和 4 类身份行为断言使用 backup 所属 commit 的版本并全部通过。
- 当前 main 的新增断言也通过；若 candidate 通过但 current main 失败，gate 仍为 blocked。
- 没有读取或导出客户行；没有触发 Auth email、webhook、cron、worker、Storage、DNS 或公开流量。
- Local target 已删除；provider clone 已按单独批准记录保留或删除。处置失败时 gate 为 blocked。
- 完成记录包含全部负责人、审批单、时间、tool versions、backup/restore ID、完整性模式、结果与限制。

## Migration 失败时的立即停止规则

任一 migration command、statement、constraint validation 或 post-migration assertion 非 0 时：

1. 立即停止 release；不执行后续 migration、应用部署或流量切换。
2. 不盲目重试，不运行 `supabase migration repair`，不修改已应用 SQL 文件，不把失败 migration 标记为 applied，不执行 linked/production reset，也不原地 restore source environment。
3. `incident_commander` 记录 failed migration ID、UTC、命令版本、数据库 error class、已应用 migration ledger 和 metadata-only catalog diff。不得记录原始客户行、database URL、token、邮箱、姓名或可能包含这些内容的完整 error payload。
4. `database_owner` 判断 PostgreSQL transaction 是否完整回滚，还是存在 partial state。只依据 migration ledger 与 catalog，不依赖 Git 状态或 UI 文案。
5. 冻结当前 migration artifact 和 SHA-256；保留经过验证的 backup ID、隔离恢复结果和 assertion record。`git revert` 只改变仓库文本，不能撤销远端 SQL、恢复数据或移除 migration ledger 记录。
6. 如果无法在不扩展风险的前提下确认状态，保持 release blocked，由 `incident_commander` 升级；不要在 production 即兴修复。

本地工具已验证这条控制流：当前 main 的 intake assertion 失败后，后续 private-RLS assertion 被标记为 `not_run`，工具仍只删除自己创建的 target。

## Forward-fix 流程

1. `forward_fix_owner` 从失败后的实际 ledger/catalog 状态设计一个 ID 晚于所有已应用 ID 的新 migration；绝不重写旧文件。
2. 使用 expand/backfill/switch/contract。新增列先允许现有数据安全存在；只回填有证据的值；需要数据验证的约束优先 `NOT VALID`，在隔离 restore 上审查失败记录后再显式 `VALIDATE`。
3. 新 migration 必须保留已应用的 location/address、Auth/RLS、Storage metadata 和 provider-specific role/extension 行为。不得因为 candidate DDL 可幂等执行就把旧 timestamp 强制写入 remote ledger。
4. 为原失败、partial state、重复执行和 4 类身份行为增加聚焦断言。在 fresh disposable database 和“精确 provider backup 的隔离 restore”上分别执行完整 migration chain、forward-fix 与 post-migration 验收。
5. 更新 evidence record：失败 migration、forward-fix ID/SHA-256、backup/restore ID、全部测试、blocking drift、负责人和限制。
6. `database_owner`、`release_owner`、`security_reviewer` 和 `forward_fix_owner` 对精确 target、migration ID、维护窗口与停止规则重新批准。旧批准不能自动覆盖新 SQL。
7. 只有获批 operator 在命名窗口应用这一条 reviewed forward migration；完成后立即复跑 migration ledger、catalog、RLS/grants 和业务断言。任何不一致再次触发停止规则。
8. 如果 forward-fix 不安全，保持 live target 不变并先在隔离 clone 评估 provider restore。production restore 是独立灾难恢复决策，不是普通 migration rollback。

## 上线前仍未完成的风险

- production backup/restore、RPO/RTO 和保留策略未批准或验证。
- staging 只验证了 synthetic Storage object 恢复；真实 production object inventory、
  versioning/retention 和批量 restore 未执行。数据库 backup 不能覆盖该缺口。
- physical backup/PITR 在 Free 不可用；如果 production 需要更短 RPO/RTO，必须先
  批准相应费用和隔离恢复演练。
- provider clone 上的 extensions、webhooks、Realtime、network restrictions 和费用
  处置未验证；当前逻辑恢复证据不覆盖这些 provider settings。
- `migration_baseline_status=canonical_staging_reconciled_production_pending`；M1
  staging pass 不代表 production-ready。

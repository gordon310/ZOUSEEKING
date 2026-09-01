# 生产发布集成决策

审查日期：2026-09-02

## C01 基线

- 集成工作区：新建隔离分支 `codex/production-release-v1`。
- 当前基线：`789f127`；上游参考 `origin/main@789f127`。
- 本地 `main@aca2a334` 与 `origin/main@789f127` 无共同祖先；禁止直接合并两个 lineage。
- `origin/main` 中的 renovation API 暂不纳入第一阶段，列为独立候选。
- 主工作区存在用户未提交改动；已在仓库外保存 tracked diff 与 untracked inventory，本次不触碰、不清理、不覆盖。
- 工作区中已有的 `test-results/` 等生成目录不纳入发布集成，也不删除。
- 本次仅进行离线文件集成与验证；不执行数据库、Auth/RLS/Storage、部署、DNS、billing 或 destructive 操作。
- 生产发布仍为 **BLOCK / NOT AUTHORIZED**；未执行任何 live provider 操作。

## 候选处置规则

1. 仅将已明确归属、能通过离线验证且符合第一阶段 allowlist 的文件标记为 `integrated`。
2. 依赖数据库基线、provider 证据、真实权限或付费服务的候选标记为 `deferred`，并指向后续 C 编号。
3. `rejected` 仅用于违反数据权利、秘密管理或发布范围的候选；当前没有候选需要该处置。
4. 不复制 secrets、`.env`、缓存、测试结果、生成媒体或未审查的整棵工作树。

## 当前决策

第一阶段只保留 `consumer_intake_preview`：匿名 intake、受限免费预览、可追溯的离线/合成 smoke。会员、收费、配额、历史库、真实生产数据、renovation API 及 provider 级发布证据必须通过后续闸门后才能进入正式 V1。

## C02 执行证据

- 已集成 FastAPI release allowlist、ADR-0002 机器契约、Edge/local worker 默认冻结、B/admin 浏览器网络门闩与 Render phase 配置。
- `tests/architecture`、intake API、staging smoke 与 worker 单元测试：`36 passed`。
- Edge Node 测试：`2 passed`；相关 JavaScript `node --check` 通过。
- Playwright release-scope 浏览器测试：`2 passed`。
- 生产发布仍为 **BLOCK / NOT AUTHORIZED**；未执行任何 live provider 操作。

## M0 执行证据（2026-09-02）

- 已运行 `git fetch --prune origin`，并从最新 `origin/main@789f127` 建立隔离分支 `codex/production-release-v1`。
- 已为新基线补充根目录 `.gitignore`，覆盖本地虚拟环境、缓存、测试结果、生成输出、Supabase CLI 状态和环境配置。
- 本地未提交 UI 改动没有批量复制：它们与候选基线存在内容差异，其中部分会移除 release-boundary 与注册同意控件，因此列为 deferred，等待独立代码审查。
- renovation 源文件已在上游基线中存在；本次不重复复制，也不将其误标为第一阶段能力。
- 新基线离线验证：Python `253 passed`；架构 manifest/authoritative policy `12 passed`；compileall、JavaScript syntax、release policy、schema ownership、post-launch review 和 `git diff --check` 通过。
- 使用已安装的本地 Playwright runner 完整回归两次，均为 `33 passed`；首次尝试出现的单个登出用例失败未能复现，未修改产品代码。
- M0 只建立可审阅的统一基线；数据库、provider、真实用户和生产部署仍保持原有阻断状态。

## C03 执行证据

- canonical 11-file history fresh reset：exit 0；migration ledger 为 11 条且顺序完整。
- `supabase db lint --local --level warning`：`No schema errors found`。
- fresh-reset schema/RLS 五组 assertions：全部 exit 0。
- custom-format dump 恢复到新建 disposable database 后，五组 assertions：全部 exit 0。
- `migration_baseline_status` 更新为 `canonical_local_pass_live_reconciliation_required`；staging drift、provider backup/clone、later-ID forward-fix 与 live approval 仍未完成。

## C04 local-only 执行证据

- `tests/unit/test_database_recovery.py`：`8 passed`。
- custom-format artifact checksum 与 `pg_restore --list`：通过，源 PostgreSQL `17.6`、pg_dump `18.6`、TOC `1072` 条目。
- `database_recovery.py drill`：`gate_status=pass`；foundation、property-intake、provenance/metric、private-RLS、V1 identity 五组 assertions 均 `pass`，`cleanup_result=pass`。
- 该证据仅覆盖本机 synthetic/empty 数据；未创建或读取 staging/production provider backup，未执行 Storage object backup、clone restore、forward-fix 或 live SQL。

## C04 provider 预检结果

- staging physical backup：无可用记录，PITR 未启用。
- Storage `property-intake` bucket：对象数为 `0`；无需执行对象复制，未读取对象内容。
- 按已确认的 `JPY 0` 费用上限，未启用任何可能收费的备份/clone 能力。
- C04 的 provider backup 与隔离 clone 仍为 **BLOCKED**；不执行 C05 的 staging forward-fix 或任何 live migration。

## C23 执行证据

- 已集成 Render PostgreSQL future migration ADR 与非执行入口；默认结论为 `render_postgres_migration=not_approved`，不更换连接串、不创建数据库、不迁移数据。
- 已集成 30/60 日 production 聚合 SLO/容量/成本复盘门槛；当前 `blocked_pre_production`，没有 production hostname、真实流量或客户内容读取。
- 机器检查 `python3 scripts/check_post_launch_review.py`：`PASS`；该 PASS 只证明阻塞状态未被误标为生产完成。
- 真实 PostgreSQL/provider、备份恢复、Render cold start、CDN、durable worker backlog、traced profile 和优化前后对比均为 `NOT_ASSESSED`；C23 不升级为 production-ready。

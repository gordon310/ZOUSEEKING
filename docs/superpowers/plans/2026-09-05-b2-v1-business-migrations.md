# P1 · V1 业务域 Forward Migration 设计冻结（B2）

日期：2026-09-05 · 负责人：Hermes（B2 代理执行） · 状态：**字段冻结，已评审入库（main `2e00113`，2026-09-05）；应用前必须过 baseline gate**

> 权威依据（均已入库 main）：`docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md`（V1 领域规格）、`docs/superpowers/specs/2026-08-31-stripe-billing-boundary-design.md`、`docs/release/usage-ledger-offline-contract.md`、`docs/release/account-controls-offline-contract.md`、`docs/superpowers/plans/2026-08-29-v1-contract-migration-baseline.md`（Task 7：每域一个 forward migration，测试先行）。实施分解按规格 §16 的 2–7 子项目映射到 5 个迁移文件。
> 红线：数据字段已冻结——本组迁移落库后，任何字段变动只允许新增 forward migration。浏览器/前端一律不得写服务端管理字段。

## 迁移集（编号连续，文件在 main，应用 gated）

| 文件 | 域（规格 §16） | 建表 |
|---|---|---|
| `20260905000100_v1_organizations.sql` | 2. 身份/机构/席位 | organizations, organization_members（≤5 active 席、单 owner 部分唯一索引） |
| `20260905000200_v1_products_subscriptions.sql` | 3+4. 产品价格/订阅/客户 | product_prices（3 产品 × 6 币种 × price_version）、billing_customers、subscriptions |
| `20260905000300_v1_usage_ledger.sql` | 3. 原子用量 | usage_quotas、usage_events（append-only+幂等指纹）、usage_idempotency |
| `20260905000400_v1_service_tasks_contacts.sql` | 5+6. 任务池/联系授权 | service_tasks、task_applications（单匹配部分唯一索引）、task_status_history、contact_consents |
| `20260905000500_v1_finance_admin_audit.sql` | 4+7. 财务/审计/后台角色 | payment_orders、refunds、payment_events（webhook 幂等，只存 payload 哈希）、internal_role_assignments、audit_events（append-only） |

配套：`tests/sql/test_v1_<域>.sql` 各一份（psql DO 块存在性/RLS/约束断言；四身份行为矩阵待 baseline gate 后补全）。

## 冻结的关键口径（勿改）

- **金额**：一律 `amount_minor` integer（最小单位）+ `currency text(3)`；币种集合固定 `CNY/HKD/TWD/MOP/JPY/USD`，首发仅发布 CNY/JPY/USD；无本地价地区不可购；禁止客户端汇率换算。
- **产品代码**：`risk_report_single`（payment，CNY500/JPY100/USD99 minor）、`c_plus_monthly`（CNY4900/JPY990/USD990）、`b_data_pro_monthly`（CNY19900/JPY3999/USD3990）。
- **Scope**：C 端权益属个人（user），B 端属机构（org）；额度机构共享，B 机构 ≤5 活跃成员；角色仅 `owner`/`member`。
- **用量**：UTC+8 自然日/月；append-only 事件 + 幂等指纹去重；consume/reserve/commit/release/reversal；容量校验数据库原子执行；冲正新增事件不改历史。
- **任务**：一任务最多一匹配；状态机 draft→open→matched_pending_consent→in_progress→completion_pending→completed + cancelled/expired/closed_unconfirmed/suspended；申请 withdrawn/rejected/match_expired（72h）。
- **隐私**：邮箱双向授权独立同意；授权后才可见（C 用户 + B 机构 owner/负责成员）；72h 未双方授权匹配失效；30 天后停止展示；匹配/证据保留 3 年；公开任务禁 PII/精确地址。
- **审计**：role/套餐/额度/退款/任务/授权/价格变更全入审计日志；日志禁完整邮箱/令牌/支付凭证/raw payload/异常堆栈；后台角色逐项授予（含 super_admin），无万能 admin 布尔。
- **RLS**：业务表全部 enable；匿名零权限；authenticated 仅读自身 scope；服务端管理字段（等级/额度/状态/归属/退款）浏览器不可写；service_role 全权；webhook 事件 id 幂等去重。

## 应用门禁（2026-09-05 状态更新）
- ✅ **staging 已应用 V1×5**（2026-09-05 用户批准；表 22→39，39/39 开 RLS，0 裸表；0904 wip 保持 pending 未推）
- ⏸ **production：未配置/未触碰**（维持原状）
- 后端 store/port 实现已完成（billing/usage 适配器，main `4712adf`）；**运行时接线**（env gate 开启指向 DB 适配器）随后台真实化批次推进
- 应用方式记录：`db push` 前临时移出 0904 文件 → push V1×5 → 还原（git 树无净变化）

## 评审清单（2026-09-05 已勾选）
- [x] 与现有 23 表无重名/无 FK 悬空；编号顺序符合依赖（00100→00500）
- [x] 风格一致：DO 前置检查、text+CHECK 枚举、uuid pk、RLS+revoke+最小 policy、索引有据
- [x] 无 `using(true)`/`with check(true)` 于业务表；authenticated 无越权写
- [x] 每表 ENABLE RLS（17/17）；匿名/认证 grant 正确；service_role 全权
- [x] 测试文件为可执行 psql DO 块断言（00200–00500 已在一次性 Postgres 容器真实验证；四身份行为矩阵待 baseline gate 后补）
- [x] 后端对接：billing store（PostgresBillingStore）+ usage DB ledger（PostgresLedger）——已实现并入库（main `4712adf`，2026-09-05；真库验证 160 passed；接入仍走 env gate）
- [ ] task/consent 服务——**延后至 P4（随小象数据 B 端）**：任务池与邮箱授权前端仍为 demo，C/B 端闭环未开工前不建服务层

---

## 增补批（2026-09-05 用户批准"两项都做"）

### 增补 A · `20260905000600_member_status.sql` — 会员状态
- `user_profiles.status text not null default 'active'` + `check (status in ('active','suspended'))`（列级）
- **列级 REVOKE**：`revoke update (status) on public.user_profiles from authenticated`（防 29000100 的 profile update policy 被借道自改状态）+ 注释服务端管理
- admin 写端点：`POST /api/admin/members/{user_id}/status`（member_ops|super_admin；success 写 audit `admin.member.status_changed`；同值幂等返回 200）
- 前端：会员页签"暂停/恢复"按钮 live 化（member_ops+super_admin 可见可用，403 提示）

### 增补 B · `20260905000601_collection_runs.sql` — 采集任务域
- `collection_runs(id uuid pk, source_key text not null, source_type text check('authorized_csv','official_open','partner','user_submitted','aggregate_authorized'), status text check('queued','running','succeeded','failed','cancelled') default 'queued', rows_collected int default 0 check>=0, snapshot_hash char(64), error_message text, operator_user_id uuid null refs auth.users on delete set null, started_at timestamptz, completed_at timestamptz, created_at default now(), check(completed_at is null or started_at is not null))`
- 索引：`(status, created_at desc)`、`(source_key, created_at desc)`
- RLS：service_role 全权；authenticated 零；后台经服务端读（沿用 internal 域惯例）
- admin 端点：`GET /api/admin/collection/runs?status=&source_key=&page=`（member_ops|data_ops|super_admin）；`POST /api/admin/collection/runs`（data_ops|super_admin 入队 queued，写审计 `admin.collection.queued`；不在此批执行采集——worker 执行器 = P1 尾单独单元）
- 前端：采集页签 live 列表（状态/行数/哈希/错误）+ "发起采集"表单（data_ops 可见）；审核子流程待 worker 单元后接
- 依赖说明：source_key 语义对齐 `configs/jphouse_23ku/<ward>.json` 等本地配置键与 `data/source_registry.json`；registry 入 DB 不属本批

> 两批均为 forward-only；应用 staging 需单独批准（repair/push 惯例同前）。

> **应用状态（2026-09-05）**：00600+00601 已由用户批准应用 staging ✓（20 条 history，仅 0904 wip 剩 pending；user_profiles.status 列级 revoke 生效，authenticated UPDATE 权限=0；collection_runs RLS on；public 表 40 张）。production 未触碰。

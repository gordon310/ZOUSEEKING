# 29000100 intake-policy chain-order 缺陷评估(证伪,2026-09-06)

## 结论

`docs/superpowers/plans/2026-09-05-staging-baseline-execution.md` §4 登记的
"29000100 fresh-install 会 drop 掉 25000400 给 intake 表建的 policy 且不重建"
**前提不成立,无需 forward-fix migration**。

## 证据

### 1. 代码事实:canonical migrations 从未给 intake 表建 RLS policy

- `20260825000400_property_intake.sql`(232 行):建表
  (`analysis_sessions` / `project_inputs` / `project_fields` /
  `project_field_evidence` / `free_previews` / `intake_rate_limits`)、索引、
  `revoke all ... from anon, authenticated`、触发器函数与行级 trigger,
  以及 **enable row level security**——全文无任何 `create policy`。
- `20260828000100_property_photo_location.sql`:同样零 `create policy`
  (project name/坐标/候选字段与 owner-scoped indexes)。
- 全仓检索(supabase/migrations + backend/sql legacy):
  对上述 6 张表的 `create policy` 数量 = 0。

### 2. 运行事实:fresh-install 整链应用后 intake 表无 policy 缺失

在 disposable PostgreSQL(容器 jpd_member_status_pg)上按文件名序整链
应用全部 21 个 canonical migrations(含 29000100 的 drop-all + 重建),
实测:

| 表 | RLS | policies |
|---|---|---|
| analysis_sessions / project_inputs / project_fields / project_field_evidence / free_previews / intake_rate_limits | enabled | **0** |

其余 public 表(24 张)经 29000100 重建后均持有各自 policy ——
29000100 的 drop-all 循环对 intake 表无可 drop(从未存在),重建集也不
包含 intake(设计如此)。

### 3. 语义:0 policy + RLS enabled = deny-all 内部表,属有意设计

intake 表只经可信后端(service_role / 后端池)读写,`revoke all` 已把
anon/authenticated 拒之门外,RLS enabled 且零 policy 进一步保证
即使未来 grant 漂移也无匿名通道。**不存在"缺失"**;若按原登记补一条
重建 policy 的 forward-fix,反而会为 authenticated 打开不该有的访问面。

## 对 staging 描述的更正

§4 原文"staging 的 intake/照片定位 policy(25000400/28000100 所建)当前
工作正常"有误:这两个迁移从未建 policy。staging 上 intake 表的行为正常
是因为同样遵循 revoke-all + 内部访问,而非存在 policy。

## 处置

- 不新增 migration(避免无谓 policy 扩大暴露面;红线:字段冻结、最小授权)。
- 本评估即结论记录;原 §4 遗留项视作已复核关闭。
- 后续如产品改变 intake 访问模型(如 C 端直连读表),再以独立 forward
  migration 显式加 policy,并配套 RLS 测试。

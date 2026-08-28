# Supabase 前向迁移历史

`supabase/migrations/` 是本项目 Supabase PostgreSQL 的唯一前向迁移历史。

## 当前状态

当前状态必须记录为：

```text
migration_baseline_status = reconciliation_required
```

目录中当前最早的业务文件是 `20260825000400_property_intake.sql`。它依赖 `auth.users`、`public.properties` 和 `public.residential_details`；这些基础表目前没有由该目录中的更早 migration 创建。因此，当前目录还不能从空库完整重建 staging schema。

这是一个依赖尚未进入迁移历史的基础表的 migration chain。

已应用的 migration 文件不可修改。任何修复都必须新增更晚的 forward migration，不得覆盖历史含义。

## V1 门槛

基线协调完成前，不得增加 V1 业务迁移。

后续 baseline reconciliation 计划必须：

1. 从审核后的仓库 SQL 和只读 staging schema inventory 推导缺失基础表；
2. 新增确定性的早期 migration，不改写已经应用的文件；
3. 在空的本地 Supabase 完成 fresh reset；
4. 运行 foundation、intake，以及匿名/owner/other-user/service-worker 的 RLS 断言；
5. 对比不含客户数据的 schema drift；
6. 定义 backup/restore 和 forward-fix 方案；
7. 取得任何 linked migration history repair 或 push 的明确批准。

在该计划完成前，不得执行：

```text
不得执行 linked repair、db push 或 production reset
```

也不得加入会员、计费、任务、联系授权或后台 schema。

## 提交规则

- 新 schema 变更只能新增到本目录。
- 不在应用启动时执行 schema 初始化。
- 不把 `backend/sql/`、旧 restore 包或线上 schema dump 当作 migration history。
- 每个新 migration 都必须配套约束、回滚或 forward-fix 说明、聚焦 SQL 断言和受控发布步骤。

# Staging Migration Baseline 收尾执行方案（P0.4）

日期：2026-09-05 · 状态：**待用户批准后执行** · 目标库：`zoubeacon-staging`（ref `fnogxuytbabxmqousifh`）· 只动 migration history，不重建对象

> 本方案基于 09-05 只读 parity + 冲突扫描（证据全在本机 /tmp 脚本输出）。

## 1. 现状（staging 实测）

- 已应用（5）：`20260825000400` `20260827000500` `20260828000100` `20260902000100` `20260902000200`
- 待处理（13）：`20260824000100–00700`（7）+ `20260829000100` + `20260904000100`(wip) + `20260905000100–00500`(V1×5)
- public 22 表全部 ENABLE RLS；24000xx 基线迁移要建的表（queries/properties/… 16 张）与函数（set_updated_at、is_service_role、prevent_*、enforce_published_source_rights 等）**在 staging 已全部存在** → staging 是 08-24 前旧 setup 跑出来的同源库，只是 history 没记录。

## 2. 处置矩阵

| 迁移 | 处置 | 理由 |
|---|---|---|
| 24000100–24000700（7） | **repair-mark applied**（仅写 history） | 对象已存在（parity 证实）；真跑会 CREATE 冲突/重复约束 |
| 29000100 baseline_access_contract | **repair-mark applied** | 内容=drop 全部 policy 后重建 canonical；staging 的 intake/照片定位 policy（25000400/28000100 所建）当前工作正常，真跑会**破坏性删除**。修复语义问题另行 forward-fix（见 §4） |
| 20260904000100（renovation wip） | **保持 pending** | B1/P2 联调时再应用 |
| 20260905000100–00500（V1×5） | **保持 pending** | baseline 收尾后才可应用（V1 gate，另批批准） |

## 3. 执行命令（批准后运行，全部带 --db-url 指向 staging pooler）

```bash
cd /Users/gordonmac/GordonDev/JPPropDIs
export STAGING_URL='<pooler 连接串, 仅本次会话>'

# 3.1 repair-mark 24000xx（7 条）
supabase migration repair --status applied \
  20260824000100 20260824000200 20260824000300 \
  20260824000400 20260824000500 20260824000600 20260824000700 \
  --db-url "$STAGING_URL"

# 3.2 repair-mark 29000100
supabase migration repair --status applied 20260829000100 --db-url "$STAGING_URL"

# 3.3 验证: history 应与 main 的"已应用集"一致
supabase migration list --db-url "$STAGING_URL"
supabase db push --dry-run --db-url "$STAGING_URL"   # 应只剩 0904 + V1×5 待处理
```

> repair 只 INSERT schema_migrations history 行，**不执行任何对象 DDL**；风险 = 可回滚（repair --status reverted 可撤销记录）。

## 4. 遗留问题（登记，不阻塞本收尾）

- **29000100 链语义**：对全新库整链应用时，它会在链尾 drop 掉 25000400 给 analysis_sessions/project_*/free_previews/intake_rate_limits 建的政策且不重建 → 全新库（未来 production）可能复现 intake RLS 缺失。需 Codex/架构会话评估：在 29000100 之后补一条 forward-fix，重建 intake/session 所需 policy（或确认其不依赖）。
- Render staging 部署与本次无关（migrations 独立于应用部署）。

## 5. 批准清单

- [x] 用户批准执行 §3.1+3.2（两处 repair write）——2026-09-05 已批准
- [x] 执行结果（exit=0 ×2）：`24000100–24000700`、`29000100` → repaired applied（仅 history 行）
- [x] 验证：`migration list` 13 条 local=remote 一致；`db push --dry-run` 仅剩 6 条待处理（`20260904000100` + V1×5，全部按 gate 有意保留）
- [x] 本记录随 commit 入库（docs）

## 6. 执行后事实（2026-09-05）

- staging migration history = 13 条已应用，与 main 的 24000xx→20260902xx 链完全一致；对象零改动（repair 只写 `supabase_migrations.schema_migrations`）。
- 待处理（有意）：`20260904000100`（B1/P2 联调应用）、`20260905000100–00500`（V1 域，另批 gate）。
- §4 遗留：29000100 对全新库整链应用的 intake-policy 缺陷 → 待架构 forward-fix 登记。

## 7. 备份恢复演练豁免决策（2026-09-05，用户批准）

本次 baseline 收尾采用 **repair-mark 方式**：仅 INSERT `supabase_migrations.schema_migrations` history 行，**零对象 DDL、零数据操作**；回滚 = `supabase migration repair --status reverted <id> --db-url <url>`，秒级且无对象风险。备份/恢复演练针对"真跑 migration 的破坏性重建"场景，对本次 repair 操作**不适用 → 豁免**。`docs/release/rollback-checklist.md` 保持模板态，待 P3 production migration（真跑对象 DDL）前按 C01–C14 门禁执行备份→恢复→验证。


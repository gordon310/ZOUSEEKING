# 实时认证配额与免费预览设计

日期：2026-09-14

## 目标

将 `free_preview`、`query`、`report`、`stats_query`、`export_row` 五个消费点统一到一个服务端配额 helper。helper 必须在消费所在的同一 PostgreSQL 事务内，按 `require_user` 得到的身份解析当前 plan，锁定并实时读取当前生效的 `plan_entitlements(metric, period)`，把该值同步到 `usage_quotas.limit_units`，再原子判断并消费；管理员改库后下一次真实请求直接采用新值。

## 不可变边界

- 新 migration 只能新增表外对象、索引、约束、函数、触发器或必要的新列；不得 `drop` 或修改任何既有约束、列、策略。
- 不修改既有数据行；种子/验收数据使用独立测试身份和清理事务。
- 既有字段冻结。免费预览沿用现有 `analysis_sessions`/`free_previews` 字段，以新增服务端消费事件和幂等指纹实现计费，不添加客户端身份字段。
- 不把请求体 `username`、`owner_user_id` 或 session token 当作计费身份；身份唯一来自 `require_user`。

## 方案

新增 `backend/app/usage/quota.py` 作为唯一消费入口，接口为：

```python
async def consume_current_entitlement(
    conn: asyncpg.Connection,
    *,
    user: AuthUser,
    metric: str,
    period: str,
    units: int,
    idempotency_key: str,
    fingerprint: str,
    scope_key: str | None = None,
) -> QuotaConsumption
```

调用者必须已经处于事务中。helper 先解析个人或组织 scope 与 plan，按 `effective_from desc, created_at desc` 选当前 active entitlement；随后对目标 `usage_quotas` 行执行插入/锁定、把 `limit_units` 更新为 entitlement 值，再在同一行锁下检查 `consumed + reserved + units <= limit`。同一 scope/kind/operation/key 或 fingerprint 重放返回 duplicate，不重复增加计数；容量不足抛出统一 `QuotaExceeded`，路由映射为 HTTP 429。

五个消费点统一映射：

| 路径 | metric / period | 幂等来源 |
|---|---|---|
| `POST /api/intake/sessions/{id}/preview` | `free_preview / month` | 同一认证 session 的稳定 fingerprint |
| `POST /api/query` | `query / month` | 用户 + 规范化 query key |
| 报告成功落账 | `report / month` | 用户 + report query key |
| `POST /api/analysis` | `stats_query / month` | 用户 + 请求内容 fingerprint |
| `POST /api/exports` | `export_row / month` | 用户 + export 内容/结果 fingerprint |

`free_preview` 端点改为 `Depends(require_user)`；仍要求现有 `X-Analysis-Session`，并校验 session 归属当前用户。由于现有 session 表已有 `owner_user_id`，创建 session 时把认证用户写入既有列；重复 preview 先由稳定 fingerprint 命中账本并返回已保存 preview，超限返回统一 429。非认证请求在配额/业务数据库之前即返回 401。

`POST /api/query` 在创建或复用报告任务的事务中消费 query 配额；相同用户和规范化 query key 已有任务时不再次计费。报告消费保留在报告成功落账事务中，并移除 C+ 的 `12` 字面量，完全读取 `plan_entitlements`。所有 legacy `pricing_plans` 限额只作为明确兼容读取，不再作为消费 helper 的当前值来源。

## Migration 策略

新增 forward migration 只建立 `free_preview` 使用 `usage_events` 所需的新增索引/函数或必要对象，并以 catalog 查询验证新增 helper 依赖；绝不重写历史 migration。若现有约束已能表达幂等性，则不新增重复约束。所有 SQL 以静态门禁测试确认不含 `drop constraint`、`drop column`、`drop policy`、`alter ... drop` 或既有策略替换。

## 错误和安全

- 未登录 preview：401；伪造请求体身份：忽略并仍按 bearer 用户计费。
- 配额不足：429，响应体使用统一 `{\"error\":{\"code\":\"quota_exceeded\",\"message\":...}}`，不写 event、不增加 consumed。
- 并发消费：同一 quota 行 `FOR UPDATE` 串行化；幂等 key/fingerprint 在事务中注册，保证不超发。
- 日/月滚动：period key 使用 UTC+8；每次请求按当前 period 新建/锁定对应 quota 行，月/日不会共享计数。
- A/B 隔离：scope 与 plan 由认证用户、profile audience 和有效组织订阅解析；不得由请求体或客户端 tier 决定。

## 测试与验收证据

先为 helper、五个 endpoint、认证边界、滚动周期、A/B 隔离、伪造身份和并发写失败测试；每组先执行并记录 RED，再实现到 GREEN。真实 staging 验收脚本在不输出密钥的情况下记录：迁移前后 entitlement 库值、两次真实 API 完整 JSON 响应、429 状态与响应体、并发成功数/429 数、匿名 preview 实际 401，以及 A/B、伪造身份和滚动期结果。密钥仅通过环境变量传入，不写入文件。


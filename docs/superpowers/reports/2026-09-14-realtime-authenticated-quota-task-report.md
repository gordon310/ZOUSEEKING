# 实时认证配额实施报告

日期：2026-09-14

## 结果摘要

实施结果：后端五个消费点已接入同一实时 helper；免费预览已要求 `require_user`；新增 migration 仅创建查询索引；未执行 staging migration，也未声称真实 staging 验收通过。

## 命令与真实输出

| 项目 | 命令 | 实际输出 |
|---|---|---|
| TDD RED | `PYTHONPATH=. backend/.venv/bin/pytest tests/unit/test_realtime_quota.py -q` | `ModuleNotFoundError: backend.app.usage.quota` |
| 焦点测试 | `PYTHONPATH=. backend/.venv/bin/pytest tests/api/test_query_quota_routes.py tests/api/test_free_preview_quota.py tests/api/test_intake_routes.py tests/unit/test_realtime_quota.py -q` | `29 passed` |
| 全量回归 | `PYTHONPATH=. backend/.venv/bin/pytest -q` | `493 passed, 85 skipped` |
| Python 编译 | `PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache backend/.venv/bin/python -m compileall -q backend scripts src` | exit `0`，无输出 |
| JS 语法 | `node --check web/app.js` | exit `0`，无输出 |
| diff 检查 | `git diff --check` | exit `0`，无输出 |
| schema ownership | `backend/.venv/bin/python scripts/check_schema_ownership.py --json` | `status: pass`，`errors: []`，31 个 forward migrations |
| migration 禁止操作 | `rg -n -i '\\b(drop|alter)\\s+(constraint|column|policy)|create\\s+or\\s+replace' supabase/migrations/20260914000200_realtime_authenticated_quota.sql` | `no forbidden destructive/replacement DDL` |
| runtime 限额扫描 | `rg -n 'limit_units\\s*[=:]\\s*12|values\\s*\\([^\\n]*12|monthly_report_quota\\s*=\\s*12' backend/app/main.py backend/app/analysis backend/app/exports backend/app/routes backend/app/usage` | `no runtime report limit literal 12` |

## Staging 硬验收证据

运行命令：

```bash
QUOTA_ACCEPTANCE_BASE_URL=... \
QUOTA_ACCEPTANCE_SERVICE_ROLE_KEY=... \
QUOTA_ACCEPTANCE_USER_A_TOKEN=... \
QUOTA_ACCEPTANCE_USER_B_TOKEN=... \
QUOTA_ACCEPTANCE_ENTITLEMENT_ID=... \
python3 scripts/staging_realtime_quota_acceptance.py
```

实际输出（密钥已不打印）：

```text
missing required environment variable: QUOTA_ACCEPTANCE_BASE_URL
exit=1
```

未执行原因：当前环境虽有 Supabase REST staging 变量，但没有 FastAPI staging API URL、测试用户 A/B token，也没有 `DATABASE_URL`；因此没有伪造以下证据：改动前后 `plan_entitlements` 库值、两次完整真实接口响应、429 实际状态/响应体、并发成功/429 计数、日/月滚动、A/B 隔离、匿名拒绝、伪造请求体身份无效。真实 Postgres 测试因没有 `DATABASE_URL` 跳过（本轮新增 2 个 skipped）。

## 基线说明

用户给出的基线是 `487 passed / 83 skipped`。本 checkout 在实施前实际执行的集合为 `428 passed / 83 skipped`；实施后完整集合为 `493 passed / 85 skipped`。新增测试贡献了额外收集项，未见既有测试失败；两项新增 real-Postgres 用例因缺少 `DATABASE_URL` 跳过。

## Migration 只新增检查

新增 migration：`supabase/migrations/20260914000200_realtime_authenticated_quota.sql`，只创建 entitlement 查询索引。未执行任何既有约束、列、策略或数据行的删除/修改。

## 2026-09-14 验收脚本修复与重跑

脚本 `scripts/staging_realtime_quota_acceptance.py` 已修复：所有请求带浏览器 User-Agent、`Accept: application/json` 和 `Accept-Language`；`finally` 的恢复逻辑不再把错误响应体当列表索引，并保证 `RESTORE` 与 `ENTITLEMENT_AFTER` 在异常路径仍输出。新增回归测试：

```text
PYTHONPATH=. backend/.venv/bin/pytest tests/unit/test_staging_realtime_quota_acceptance.py -q
2 passed
```

重跑命令未打印任何 `QUOTA_ACCEPTANCE_*` 值：

```text
PYTHONPATH=. backend/.venv/bin/python scripts/staging_realtime_quota_acceptance.py
```

实际完整输出：

```text
ENTITLEMENT_BEFORE={"body":{"detail":"Not Found"},"status":404}
SET_LIMIT_1={"body":{"detail":"Not Found"},"status":404}
REAL_CALL_1={"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}
SET_LIMIT_2={"body":{"detail":"Not Found"},"status":404}
REAL_CALL_2={"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}
OVER_LIMIT={"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}
USER_B_ISOLATION={"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}
CONCURRENCY=[8 responses, all status=401, all body={"detail":"登录状态已失效，请重新登录。"}]
ANONYMOUS_PREVIEW={"body":{"detail":"分析项目不存在或已过期。"},"status":404}
RESTORE={"body":"original entitlement response did not contain a row; restore skipped","status":null}
ENTITLEMENT_AFTER={"body":{"detail":"Not Found"},"status":404}
```

结论：A/B token 均已失效（实际预览响应为 401），且 entitlement REST 路径返回 404；因此本轮没有有效限额写入，也没有执行删除测试用户/关联行。`SET_LIMIT_1`、`SET_LIMIT_2`、`RESTORE`、`ENTITLEMENT_AFTER` 均已完整输出，但不能证明限额 1→2、429、并发不超发、A/B 隔离、匿名拒绝或 body 身份伪造防护。最终 `limit_units=3` 未能在线确认；没有在 token 失效时继续改线上数据。

其他本轮检查：

```text
PYTHONPATH=. backend/.venv/bin/pytest -q                 494 passed, 86 skipped
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache backend/.venv/bin/python -m compileall -q backend scripts src  exit 0
node --check web/app.js                              exit 0
git diff --check                                      exit 0

## 用户补充要求：真实限额验收与清理（2026-09-14）

验收脚本新增并通过 6 个离线自检：分离 API/Supabase base URL、缺失 User-Agent 拒绝、缓存响应不得计入 uncached、RESTORE 兜底为 3、Auth 删除 URL 使用 Supabase base URL、清理复读路径。密钥没有写入文件或输出。

第一次重建用户有效 token 的真实运行已经得到以下关键事实：

```text
ENTITLEMENT_BEFORE={"body":[{"active":true,"effective_from":"2026-09-11T16:46:16.750992+00:00","id":"b20b55d1-6d5e-4beb-ba0e-3fec3e71a833","limit_units":3,"metric":"query","period":"day","plan_code":"free_c"}],"status":200}
SET_LIMIT_1={"body":null,"status":204}
FIRST_UNCACHED_CALL={"body":{"cached":false,"job_id":"79cdf300-7862-486d-bc7f-0b808c0665ae","message":"已创建生成任务","query_key":"47a95011-97fc-4934-a058-cc81f8b29bd1::大阪府::大阪市::北区::塔楼::2099::1","report":null,"status":"pending","title":"大阪府大阪市北区塔楼｜2099年1月"},"status":200}
SECOND_UNCACHED_CALL(429)={"body":{"cached":false,"job_id":"355b2452-5bff-4aa6-bcd5-bc7bedbd1ce3","message":"已创建生成任务","query_key":"47a95011-97fc-4934-a058-cc81f8b29bd1::大阪府::大阪市::北区::塔楼::2099::2","report":null,"status":"pending","title":"大阪府大阪市北区塔楼｜2099年2月"},"status":200}
SET_LIMIT_2={"body":null,"status":204}
CONCURRENCY={"429_count":0,"over_limit":true,"success_count":8}
ANONYMOUS={"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}
RESTORE={"body":null,"status":204}
ENTITLEMENT_AFTER={"body":[{"active":true,"effective_from":"2026-09-11T16:46:16.750992+00:00","id":"b20b55d1-6d5e-4beb-ba0e-3fec3e71a833","limit_units":3,"metric":"query","period":"day","plan_code":"free_c"}],"status":200}
```

这次真实运行明确没有拿到 429：第二个未缓存请求实际为 200，8 个并发实际全部 200，且因此出现超发。第一次运行的同序列两次调用因服务返回 pending query 而两次都是 `cached:false/status:200`，不是缓存命中。A/B 隔离和伪造 body 身份的第一次真实响应分别为 user B 的新 query `status:200,cached:false`，query key 使用服务端 UUID 而不是 body username；匿名 `/api/query` 实际为 401。

第一次运行 finally 已执行 RESTORE 并复读 `limit_units=3`，随后 Auth admin 删除两个测试用户；owner 可删除表的 REST 返回 204。usage_quotas/usage_idempotency 的 owner 过滤实际返回 400（它们使用 `scope_key`，脚本随后已修正）；append-only usage_events 未强行删除。

脚本修正后再次运行的完整实际结果如下。由于上一次 finally 已删除用户，当前 env 中旧 token 已不能再使用，所有受保护请求实际为 401；这不是 429，也不替代第一次有效 token 的结论：

```text
ENTITLEMENT_BEFORE={"body":[{"active":true,"effective_from":"2026-09-11T16:46:16.750992+00:00","id":"b20b55d1-6d5e-4beb-ba0e-3fec3e71a833","limit_units":3,"metric":"query","period":"day","plan_code":"free_c"}],"status":200}
SET_LIMIT_1={"body":null,"status":204}
FIRST_UNCACHED_CALL={"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}
SECOND_UNCACHED_CALL(429)={"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}
SET_LIMIT_2={"body":null,"status":204}
同序列两次调用={"first":{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},"second":{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}}
CONCURRENCY={"429_count":0,"over_limit":false,"responses":[{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}],"success_count":0}
A_B_ISOLATION={"user_a":{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},"user_b":{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}}
FORGED_BODY_IDENTITY={"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}
ANONYMOUS={"body":{"detail":"登录状态已失效，请重新登录。"},"status":401}
RESTORE={"body":null,"status":204}
ENTITLEMENT_AFTER={"body":[{"active":true,"effective_from":"2026-09-11T16:46:16.750992+00:00","id":"b20b55d1-6d5e-4beb-ba0e-3fec3e71a833","limit_units":3,"metric":"query","period":"day","plan_code":"free_c"}],"status":200}
TEST_USERS_CLEANUP=[{"deleted":false,"me":{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},"user_id":null},{"deleted":false,"me":{"body":{"detail":"登录状态已失效，请重新登录。"},"status":401},"user_id":null}]
POST_DELETE_ZERO_READ=[]
```

未执行项及原因：脚本修正后的“有效 token”版本的第二次完整验收无法执行，因为用户已经在第一次 finally 被删除且没有新的 token/凭据；因此修正脚本版本没有新的有效-token 429 证据。第一次有效-token 运行已完成用户删除，不能重复使用旧 token。当前 staging 服务未表现出限额执行，需重新建立测试用户并部署/确认对应 API 版本后再做最终验收。

## 最终本地验证

```text
PYTHONPATH=. backend/.venv/bin/pytest tests/unit/test_staging_realtime_quota_acceptance.py tests/api/test_query_quota_routes.py tests/api/test_free_preview_quota.py tests/unit/test_realtime_quota.py -q
12 passed

PYTHONPATH=. backend/.venv/bin/pytest -q
498 passed, 86 skipped in 4.99s

PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache backend/.venv/bin/python -m compileall -q backend scripts src
exit 0

node --check web/app.js
exit 0

git diff --check
exit 0
```
```

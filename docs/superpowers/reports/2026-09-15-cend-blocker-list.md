# 小象避坑 C 端 — 卡点清单(2026-09-15 02:00–06:00 批次)

> 规则:**已测试过的流程不再重复测试**;每个卡点必须带证据、定位根因、标记状态。
> 本批次目标:让 C 端「提交 → 生成 → 出报告 → 可见付费入口」真正跑通。
> 代码基线:`main == origin == e7482b9`(Lightsail 已部署,api 容器已重建)。

## 一、本批次修复(已上线)

| # | 卡点 | 根因(含证据) | 修复 | 状态 |
|---|---|---|---|---|
| **B1** | 报告**从未产出过 `full_report`**,前端永远「资料不足」,付费入口不可见 | 触发器 `enforce_published_source_rights` 要求 `source_id` 指向 `rights_confirmed` 来源;而线上 `public.sources` **0 行**、生成路径又**未设置 `source_id`** → 每次 insert 抛 `published property_reports requires an authorized source` → 任务 `failed` | forward migration `20260915000100` 登记国土交通省 土地総合情報システム(政府开放数据、`rights_confirmed`);生成路径绑定来源 | ✅ 已上线(Codex live 证据:`job=completed` + `report_status=full_report` + `source_id` 非空) |
| **B2** | **第二个用户查同一地区+类型必失败**(实测撞到) | `property_reports.slug` 是**全局唯一**,而 slug 由「地区+类型」派生、不含用户 → `duplicate key value violates unique constraint "property_reports_slug_key"`,Key=(`jphouse_jphouse_23ku_港区_塔楼`);线上「港区/塔楼」已被一个测试账号占用 | slug 加 owner 命名空间 + forward migration `20260915000200`(`drop` 全局唯一 → `unique(owner_user_id, slug)`) | ✅ 已上线(线上约束实测已替换) |
| **B3** | 来源 id 被写死在代码里 | `os.getenv("JPHOUSE_MARKET_SOURCE_ID", "bf4b6d56-…")` 默认值即硬编码 UUID(违反「配置不得写死」) | 改为运行时按稳定业务键(`sources.url`)从库解析 + 60s 缓存;解析失败落**结构化错误**,不 500、不静默回退 | ✅ 已上线(容器内已无硬编码常量) |
| **B4** | 用户**永久卡死**:报告停在 `generating`,页面无入口、无报错 | 缓存状态机漏分支:线上 4 行僵尸报告(`report_status='generating'` + 任务 `status='completed'`)会被判为「等待中」→ 永不重入队 | 终态任务 + 未发布报告 → `requeue`;`insufficient_data` 仍视为合法结论走缓存(避免反复重算烧额度) | ✅ 已上线(单测 6 分支覆盖) |

测试(Codex 侧):`518 passed, 86 skipped`;compileall / `node --check` / `git diff --check` 通过。

## 二、已上线但**未做 live 端到端验证**

| 项 | 说明 |
|---|---|
| B2/B4 的线上行为 | 需要两个一次性临时账号对同一地区各生成一次、以及人为造僵尸态后验证自愈。验证脚本已备好(`/tmp/zouseeking-live-verify-task.md`),**派工因审批超时未执行** → 按「已上线、未 live 验证」看待 |
| 你的账号 | `gordon310103@gmail.com` 配额保持 **0/3 未消耗**;`1114513@qq.com` 未被动用 |

## 三、待你决策 / 待你提供

| # | 项 | 需要什么 |
|---|---|---|
| **N1** | 用户注销会报错:`usage_events` 为 append-only 且外键 `ON DELETE SET NULL` 指向 `auth.users`,删用户被触发器挡下(上线前合规项) | 认可「软删除 + 事件行匿名化」方案后派工 |
| **N2** | AWS SES 退沙盒审核 | 你确认结果(注册邮件仍 2 封/时,是上线硬依赖) |
| **N3** | 4 行历史僵尸报告(`generating`,分属 `1114513@qq.com` 与测试账号 p2test) | 修复后会在对应账号下次查询时自愈;若要我清理,先给清单待批(本批次**未删任何数据**) |

## 四、已知未修(不阻塞本次链路)

| # | 项 | 状态 |
|---|---|---|
| **C1** | Release Gate CI 红:最新 run Playwright **22 failed / 59 passed**(其余 6 job 全绿)——09-12 夜间前端重构后的断言漂移 | 任务书已存在(`~/.hermes/tmp/dispatch-pw-drift-20260914.txt`),待派工清零 |
| **C2** | `location` 接口要求 `accuracy_m`,直接调 API 会 422(前端流程不受影响) | 待确认前端是否总是传全 |
| **C3** | `pip check` 报缺 `packaging`(环境项,非产品缺陷) | Codex 报告已记录 |
| **C4** | 迁移未录入 `supabase_migrations.schema_migrations`(2026091x 起的历史实践即如此) | 卫生项,建议后续统一 |

## 五、部署与回滚

- 本次部署:push `e7482b9` → 服务器 `git pull` → `docker compose -f deploy/docker-compose.prod.yml up -d --build api`;nginx 未改(无需 force-recreate)。
- 线上库变更:① 追加 1 行 `sources`(可 delete 回滚)② 替换 `property_reports` 的 slug 唯一约束(可回滚为原 `unique(slug)`)。
- 回滚:服务器 `git checkout <上一提交>` 重建 api 容器;DB 侧约束回滚见 migration 反向语句。

# ZOUSEEKING 上线检查清单（第三批，2026-09-12）

本清单记录仓库内可复核的当前状态。`已验证`只表示本仓库文件或本次命令已证明该断言；不把代码配置、沙盒结果或旧报告当作生产证据。线上域名在本次环境中 DNS 不可解析，故线上可达性与生产状态仍是待人工确认。

## A. 已完成且已验证（仓库/离线证据）

| ID | 核实结论 | 证据 |
|---|---|---|
| A01 | 生产部署目标已在部署配置中统一为 AWS Lightsail 上的 Compose：`api`、`worker`、`scheduler`、`nginx`；Supabase 是应用数据服务。 | `deploy/README.md:1-18,50-73`；`deploy/docker-compose.prod.yml:5-59` |
| A02 | 四个主域名与 www 别名已写入 Nginx：官网 `zoubeacon.com`/`www`、C 端 `zoubeacon.app`/`www`、B 端 `platform.zoubeacon.com`、API `api.zoubeacon.com`。 | `deploy/nginx/default.conf:1-6,9-24,26-44,46-61,63-86` |
| A03 | API 代理目标是 `api:8000`，旧 Render API 不是当前 Nginx 目标；本次 `curl` 对四个域名均因 DNS 无法解析而未形成线上证据。 | `deploy/nginx/default.conf:63-85`；本次命令：`curl -L --max-time 12 ...`，结果 `Could not resolve host` |
| A04 | 当前价格模型包含 6 币种（CNY/JPY/USD/TWD/HKD/SGD）和 3 商品（单份报告、C Plus、B Data Pro），价格读取优先 `pricing_plans`/价格表，权益读取 `plan_entitlements`。 | `backend/app/billing/catalog.py:16-32,77-96,156-169`；`docs/superpowers/reports/2026-09-12-paid-user-loop-task-report.md:14-17` |
| A05 | 单份报告购买的应用代码已要求 `query_key` 并按报告标识关联订单；沙盒闭环/代码测试有报告记录，但生产支付未验证。 | `docs/superpowers/reports/2026-09-11-zouseeking-per-report-currency-task-report.md:12-18,22-30`；`backend/app/billing/routes.py:89-204` |
| A06 | 会员读取与额度摘要的实现和离线测试已记录；真实 Supabase 表、迁移和 webhook delivery 未验证。 | `docs/superpowers/reports/2026-09-12-paid-user-loop-task-report.md:19-23,56-75` |
| A07 | PWA manifest、192/512 图标、maskable 图标、apple-touch 图标、Service Worker 和 6 个 C 端 shell 页面已存在；Service Worker 明确不缓存 API/Auth/Functions。 | `web/manifest.webmanifest:1-15`；`web/sw.js:1-18,36-75`；`web/js/pwa.js:1-6`；本次 `rg --files web` 与页面声明检查 |
| A08 | 四语言代码与页面语言选择器已存在：`zh-CN`、`zh-Hant`、`en`、`ja`。 | `web/js/i18n.js:3,1753-1777`；本次 `rg -n '<option value=...' web/*.html` |
| A09 | 隐私页面包含台湾 PDPA 六项、香港 PDPO、新加坡 PDPA、日本 APPI、中国大陆 PIPL/跨境说明的多语言文案；页面仍明确是待法务/负责人确认草稿。 | `web/privacy.html:37-64`；`docs/superpowers/reports/2026-09-12-zouseeking-privacy-compliance-task-report.md:23-58` |
| A10 | 本地离线检查入口和状态契约已明确：`PASS` 必须真实命令退出 0，外部检查未执行不得改成 PASS。 | `docs/release/release-gate.md:5-14,23-70` |

## B. 待人工确认 / 发布阻断项

以下项目没有仓库或本次命令可替代的生产证据，不能由本清单代负责人勾选：

| ID | 行动项 | 完成证据要求 |
|---|---|---|
| B01 | Stripe 账户实名认证：当前有逾期任务，功能被暂停。 | Stripe Dashboard 账户状态与处理完成记录 |
| B02 | 生产 Stripe 密钥和生产 webhook 签名：当前配置仍是沙盒/示例口径。 | 生产密钥已由负责人注入受限环境；生产 webhook 签名验证与 delivery 记录；不得把密钥写入仓库 |
| B03 | 真实收款小额实测 1 笔，并核对 webhook、订单、报告解锁、退款/对账边界。 | 负责人保留脱敏支付、webhook、订单和解锁关联证据 |
| B04 | 隐私政策法务审阅，特别是台湾 2025 修法收紧跨境传输及各地区处理者/机制。 | 法务审阅意见、批准版本、生效日与政策版本 |
| B05 | Render 服务最终处置：当前挂起保留回滚；确认继续保留、恢复演练窗口或退役。 | Render 控制台状态、责任人、保留期限与回滚演练记录 |
| B06 | 四站点生产 DNS/HTTPS/健康检查与页面可达性。 | 从外部网络执行四域名请求、API `/health/live` 与 `/health/ready`，保存时间、HTTP 状态和 commit |
| B07 | AWS Lightsail/Supabase 实际 region、生产 project、Auth/Storage、备份/恢复、RLS 四角色矩阵。 | 生产目标 ID（脱敏）、备份 restore 验证、anonymous/owner/other-user/worker 结果 |
| B08 | 生产部署 commit、artifact checksum、观察窗口、告警渠道、停止条件和 rollback owner。 | 发布审批记录与部署/监控证据 |
| B09 | 生产浏览器审计（桌面、390x844、键盘/focus、console、PWA 离线回退）以及真实 smoke。 | 浏览器录屏/日志；真实资料测试需另有授权 |

## C. 上线决策条件（不替负责人作 Go/No-Go）

当前条件结论：**BLOCK / NOT AUTHORIZED**。原因是 B01～B09 仍有未闭合项，且本次无法解析线上 DNS；`production-release-evidence.json` 保持 `release_ready=false`。

允许负责人作 **Go** 的最低条件：B01～B09 每项都有真实、可追溯且与当前 commit/生产目标对应的证据；生产 Stripe 不是沙盒；法务批准当前政策；1 笔真实收款成功并能自动解锁；备份恢复和数据库/RLS/Storage/Auth 检查通过；观察窗口、停止条件与回滚目标已批准。

任何一个条件缺失、生产目标不明、支付仍暂停/沙盒、法务未批准、备份不可恢复、RLS/ownership 失败、线上健康/console smoke 失败，均保持 **No-Go/阻断**。不得通过启用旧 Edge/local worker、直接 PostgREST、手工数据库写入或把 Render staging 结果当生产证据来绕过。

## 过期条目处理

- `consumer_intake_preview` 仅作为旧阶段范围，已改为当前多站点、会员、付费报告与订阅范围；旧阶段限制（B/admin/付费路径必须关闭）不再作为当前上线断言。
- Render 不再作为当前 API/前端部署目标；仅保留为“挂起、待最终处置、可恢复回滚”的人工项。
- “全部未授权”的旧分组拆成已验证仓库事实、待人工生产门槛和决策条件；未验证项没有被打勾。
- 旧的 `render_api_service`、`web_service`、`supabase_project_ref` 空目标模板字段改为当前 provider/域名配置与明确的未验证状态；不伪造生产 ID、secret、artifact 或 health 结果。

# 小象房产项目 · BOT 编排与里程碑路线图

日期：2026-09-04 · 编制：Hermes Agent（规划/总控） · 执行：Codex CLI（各 BOT）

> **决策记录（2026-09-04 用户已确认）**：① BOT 方案 = 推荐版（4 开发 BOT + H 管家）；② 仓库策略 = 方案 A（ZOUSEEKING 一库三主线，JPPGSKILL 独立成库 gordon310/JPPGSKILL）；③ Hermes cron 已建：每周一 09:00 里程碑回顾 + P0–P4 出口前 3 天验收提醒，投递渠道 = QQ 机器人（qqbot 已连通，OpenID D6AF3…8383A）；④ P0 首批动作已启动。

> **双线分叉已解决（2026-09-04 晚）**：本地 main（root c848b09）与 origin/main（root 349e310）无共同祖先。仲裁结论与全量清单见 `2026-09-04-divergence-arbitration.md` + `2026-09-04-divergence-file-manifest.txt`。执行：origin/main 为权威基线，5 个重放 commit 并入 main 并已推送远端（`5672877`）。原工作分支与状态存于 `backup/workspace-20260904-{main,intake,originmain}`、`codex/replay-carryover`（含未部署的 renovation migration wip）。

> 本文是 Hermes 侧的项目总控文件：回答"配几个 BOT、各自边界、按什么里程碑推进、如何验收"。
> Codex 各会话只读本文件的「自己的章节 + 仓库 AGENTS.md」即可开工，无需全量上下文。

---

## 1. 现状核对（2026-09-04 实测，非推测）

| 项 | 实测结果 |
|---|---|
| JPPropDIs（= ZOUSEEKING monorepo） | 已是 git 仓库；remote = `github.com/gordon310/ZOUSEEKING.git`；`main` 存在，远端 HEAD = origin/main |
| 当前工作分支 | `codex/intake-renovation-estimate`，有**未提交**改动：`supabase/migrations/20260904000100_intake_renovation_observations.sql` + `tests/sql/test_renovation_observations_schema.sql`（装修估算相关，Codex 正在做） |
| 历史分支 | 大量 `codex/*` 短分支 + 约 30 个 worktree（多在 `~/.codex/worktrees/`，detached HEAD，可清理） |
| 部署现状 | Render staging 前端 = `056a263`；后端/SQL 新 commit `57762f5` 仍只在本地，**未部署**（progress.md 2026-09-01） |
| 数据库 | Supabase staging `zoubeacon-staging`（ref `fnogxuytbabxmqousifh`），22 张表全 RLS，migration history：25000400 / 27000500 / 28000100 / 29000100（staging 待 push） |
| JPPGSKILL | **不是 git 仓库**（根目录与 `jp-property-graphic/` 均无 `.git`）；包含 Node 拍照原型 + 可复制的 Skill 包（SKILL.md + references/ + superpowers 设计文档）→ 上线前必须先 git init 或纳入版本库 |
| 产品边界 | 已在 progress.md 确认：C 端=小象避坑/ZOUBEACON，B 端=小象数据/ZOUSEEKING，暂同一仓库按模块分界，后期可拆 |
| 采集合规 | 已有产品决策（官方/授权/受控聚合/用户提交/人工复核；禁止反爬绕过），采集脚本仍为原型，上线前需补授权、快照、告警、质量门禁 |
| 前端/报告 | 产品方已于 08-29 验收界面与报告样式（全部 `synthetic_fixture`，未接真实数据） |

**推论**：字段/界面已冻结 ✓（用户确认不再反复验证）。剩余工作集中在：数据库迁移定稿与部署、后台真实数据链路、C 端支付与发布、B 端真实化——这些正是 BOT 分工的边界。

---

## 2. 需要几个 BOT：推荐 4 开发 BOT + 1 Hermes 管家

### 2.1 总原则（为什么要这个数量）

- **少而稳**：Codex 额度有限（progress.md 已在监控额度），每个常驻 BOT 意味着持续的代码生成与上下文成本。够用即止。
- **冲突最小化**：单一 monorepo、一个 FastAPI、一套 migrations —— 并行 BOT 之间真正的冲突点是 `backend/app/`、`supabase/migrations/`、`web/`。按**目录所有权 + 迁移文件前缀 + 合并顺序**划界，比增加 BOT 数更有效。
- **B 端延后**：用户已定优先级 = 小象避坑 + 后台先上线，B 端后完善 → B 端 BOT 晚于前两者启动，避免三线同时抢同一后端。

### 2.2 BOT 清单

| # | BOT 名 | 对应产品线 | 激活时段 | 使命（一句话） |
|---|---|---|---|---|
| B1 | **ZOUBEACON** | 小象避坑（C 端） | P2 起常驻 → 上线后维护 | 拍照→定位→免费评估→深度报告的真实链路 + 支付 + APP/PWA 发布 |
| B2 | **ZOUBACKOFFICE** | 后台管理 + 数据管道 | P1 起常驻 | 采集调度/质量审核/任务派单/会员/财务真实化，为 C/B 端供数 |
| B3 | **ZOUSEEKING** | 小象数据（B 端） | P4 启动 | 区域租售比统计订阅、机构账单导出、C 端服务接单闭环 |
| B4 | **JPPGSKILL** | 日本房产识图 Skill 包 | P0 短周期 + 随 B1 联调 | git 化与发布、版本化（当前 v0.1.1）、配合 B1 的六类照片分析接入 |
| H | **管家（Hermes）** | 全项目 | 全程 | 计划/里程碑/验收门禁/跨 BOT 协调/每周进度汇总（cron），不写业务代码 |

**可选（不常设）**：`架构收敛会话`（一次性）——接手现存 `codex/migration-reconcile` 与 ADR-0001（FastAPI 为唯一业务 API、Edge/local-worker/BackgroundTasks 收敛）等未决架构债。归入 P0–P1 里程碑，由管家派临时 Codex 任务，而非新开常驻 BOT。

**不推荐** 6–8 个 BOT：monorepo + 单后端下收益递减，主要成本在协调与额度，不在写代码速度。

### 2.3 各 BOT 边界与验收（写进各分支的 AGENTS 或任务提示）

**B1 ZOUBEACON（C 端）** — 目录：`web/`（C 端页面：property-analysis/projects/project/profile?role=consumer）、`backend/app/routes/intake.py`、`renovation.py`、照片定位链路、C 端报告生成、支付/订阅（IAP 与 Stripe 适配）、发布（大陆安卓渠道 + iOS + PWA）。
验收：真实账号从拍照/上传 → 位置 → 免费评估 → 付费 → 深度报告全链路 staging 通过；无 `synthetic_fixture` 残留于 C 端展示；商店提审材料齐备。
禁止：改 B 端/后台页面布局；不经管家合并 gate 触碰共享 migration。

**B2 ZOUBACKOFFICE（后台）** — 目录：`web/admin*`、采集脚本与 worker（`scripts/`、独立调度）、数据质量/来源登记、后台 API、财务流水、会员管理、服务任务池。
验收：调度器可按节奏（房源日更/区域周更/人口月更）自动采集→快照哈希→质检→入库→告警；后台可审核/派单/查账/停复会员；全部 RLS 测试通过。
禁止：改 C 端用户流程与定价协议。

**B3 ZOUSEEKING（B 端）** — 目录：`web/`（B 端页面：data-query/organization/billing/usage/subscriptions/exports/service-tasks）、区域租售比统计服务、机构级订阅计量。
验收：机构成员/订阅/账单/导出/接单均为真实数据闭环；统计口径遵循 AGENTS（JPY canonical、median+样本数、期限与数据类标注）。
激活条件：B1+B2 上线门禁通过后才进入 P4。

**B4 JPPGSKILL（Skill 包）** — 目录：`/Users/gordonmac/GordonDev/JPPGSKILL`（独立仓库，见 §3）。
使命：git init + 首次推送；`releases/` 版本化流程；SKILL.md/references 与 B1 联调结果同步（六类照片 → 装修估算 → 证据规则）；不承接 App 业务代码。
验收：新仓库 main 干净、含 releases/v0.1.1；B1 联调改动均以新版本发布而非原地改。

**H 管家（Hermes）** — 职责：维护本文件；每周汇总各分支 diff/测试/门禁状态 → 汇报；里程碑到点发验收清单；协调跨 BOT 的 migration 合并顺序；把"用户已冻结字段"作为红线写进每次派单（**禁止再反复验证数据字段**）。

---

## 3. 仓库与分支策略（二选一，建议 A）

**方案 A（推荐）：ZOUSEEKING 一库三主线 + JPPGSKILL 独立成库**
- `github.com/gordon310/ZOUSEEKING`：`main` = 集成/发布主干（Render staging 已从 main 构建，保持不变）；B1/B2/B3 各以 `codex/zoubeacon-*`、`codex/zoubackoffice-*`、`codex/zouseeking-*` 前缀的短分支并行，**按管家排定的顺序**合入 main。
- JPPGSKILL 是独立技能包，独立仓库 `github.com/gordon310/JPPGSKILL`（根 = 当前 JPPGSKILL 目录），与 App 代码生命周期不同，塞进 App 仓库的分支只会互相拖累。
- 优点：贴合现状（codex 短分支 + main 部署已跑通）、单 staging 不打架、Skill 可独立发布版本。
- 缺点：没有"每产品一条长期分支"的视觉隔离——由目录所有权 + 分支前缀替代。

**方案 B（用户原提案）：main 下四个长期分支**
- 每个产品线一条长期分支（ZOUBeacon/ZOUZEEKINGHOUSE/ZOUBackoffice/JPPGSKILL），各自从 main 分化、各自部署。
- 代价：monorepo 内长期分叉会造成三份漂移的代码与三套部署；Render 单服务部署模型要改；合并回 main 时冲突面大。JPPGSKILL 作为分支仍受 App 仓库约束，不如独立仓库。
- 仅在"三个产品要完全独立部署/独立团队"时才值得。

> 无论 A/B，**Codex 并行必须用 git worktree**（每 BOT 一个 checkout），否则同一工作区多进程互踩。现有 `~/.codex/worktrees/` 下 20+ 个 detached 陈旧 worktree 建议先清理。

---

## 4. 里程碑时间线（2026-09-04 起，CST）

**P0 · 基线收尾（09-04 → 09-08）— 负责人：H + 一次性 Codex 会话 + B4**
1. JPPGSKILL：git init + 首次提交 + 建远端仓库并推送（补 .gitignore：node_modules、sqlite、.certs、dist、releases 产物）。
2. 结构梳理：产出仓库地图（源码/生成物/数据边界清单），生成物目录（data/output、web/library、releases）确认不进 Git 或按白名单管理。
3. 清理陈旧 worktree（`~/.codex/worktrees`、/private/tmp 下 prunable 项）。
4. 数据库 baseline reconcile：把 `20260904000100_intake_renovation_observations.sql` 等本地新 migration 与远端 history 对齐（staging 应用 + 备份恢复演练，production **不动**）。
5. 部署基线：本地后端 commit `57762f5` 系列按门禁部署到 Render staging，/health/ready 通过。
✅ 出口：两端仓库远端可见且结构干净；migration history 唯一且 staging=本地；门禁模板 C01–C14 可用（已有，C12/C13 待闭合）。

**P1 · 数据库定稿 + 后台真实化（09-08 → 09-28）— 负责人：B2 为主，H 把关字段冻结红线**
1. 冻结数据字典（用户红线：**不再反复验证字段**）；补完冻结表清单的剩余 forward migration：会员/机构/成员、订阅与用量计量、服务任务池、财务流水、采集任务与来源登记、支付订单（含币种，见 §6.2）。
2. RLS 身份矩阵 + SQL 测试全绿（匿名/本人/他人/特权 worker 四角色）。
3. 采集管道真实化：来源登记（rights/robots/rate limit/保留期）→ 调度（房源每日、区域每周、人口/土地/灾害每月或事件触发）→ 原始快照+哈希 → 解析 → 质检 → 人工复核 → 仓库 → 指标；失败告警。
4. 后台管理平台接通真实数据（不再 synthetic_fixture）：采集审核、任务派单、会员停复、财务流水、发布前检查。
✅ 出口：后台全部功能真实数据可跑；调度器按节奏出数并留证据；SQL/RLS 全绿；数据字典零改动。

**P2 · 小象避坑 C 端上线准备（09-15 → 10-18，与 P1 尾部并行）— 负责人：B1 + B4 联调**
1. 后端权威化收敛（架构债，依赖 P0/P1 的 ADR-0001 执行）：新单项目分析只走 FastAPI，Edge/worker 冲突路径退役或收紧。
2. JPPGSKILL 联调：六类照片 → 位置（拍照定位已在 08-28 落地，含 `PUT /api/intake/sessions/{id}/location`）→ 装修估算/房产识别分析协议接入；`asset_type` 等冻结字段正式 migration（前端门槛已就绪）。
3. 免费评估/深度报告：从 synthetic_fixture 切到真实生成链路 + 证据定位输出（AGENTS 要求），报告生成放 durable worker。
4. 支付：免费→付费转化（IAP 为主 + 网站 Stripe），多币种显示与汇率版本化（见 §6.2）；定价服务 `services/pricing.py` 已存在，接真实价格与订单。
5. 发布通道：大陆安卓渠道（应用宝/华为/小米/OPPO/vivo）+ iOS（中国区与海外区）+ PWA；隐私政策/用户协议/免责声明；合规清单（ICP、个保法、算法/深度合成备案评估——拍照 OCR/视觉分析涉及）。
6. 上线文档：商店截图、物料、客服与退款流程。
✅ 出口：staging 全链路（匿名→免费预览→注册→支付沙箱→深度报告）真实通过；提审材料齐备。

**P3 · 试运行 + C 端/后台同时正式上线（10-19 → 11-中）— 负责人：H 门禁 + B1/B2**
1. 试运行：种子用户 + 真实房源有限范围（标记试运行数据），收集问题清单。
2. production migration 应用（备份→forward→验证→回滚预案，按 C01–C14 模板执行）；生产 RLS/密钥/额度审计；监控与告警（结构化日志、错误率、支付对账）。
3. Go/No-Go：全部阻断项闭合（C06 provenance、C11 预算、C12 CI、C13 live smoke 等按模板复核）。
4. **小象避坑 APP + 后台管理平台同时正式上线**（用户核心要求）。
✅ 出口：双端生产运行 + 发布公告；首周数据/支付/任务观察报告。

**P4 · 小象数据 B 端上线（11-中 → 12 月）— 负责人：B3**
1. 机构/成员/订阅/账单/用量/导出/接单真实化（前端 08-29 已完成，接后端与计量）。
2. 区域售租比分析用真实数据源出报告（多期趋势、median、样本量与数据类标注）。
3. 与 C 端服务任务池打通（后台派单 → B 端承接/转交 → C 端交付）。
✅ 出口：小象数据平台正式上线，机构客户 1–2 家试用。

**P5 · 持续（2027 Q1）**：多币种支付扩展（CNY/HKD/SGD/MYR 渠道适配，见 §6.2）；多语言运营内容；数据源授权矩阵扩展；合规迭代。

---

## 5. 上线顺序（兑现用户要求）

```
P0 基线 ──→ P1 数据库+后台真实化 ──╮
                                  ├──→ P3 试运行 → 【小象避坑 + 后台管理 同时正式上线】
P2 C端上线准备（P1 尾部并行）──────╯
                                              └──→ P4 小象数据上线
```

---

## 6. 三个顾虑的落地映射

### 6.1 合法数据抓取与统计分析
已有产品决策即答案，缺的是执行：
- 采集只走四类合法来源（官方/地方公开、已授权合作、受控网页聚合、用户主动提交+人工复核）；每个数据源登记 rights/robots/rate-limit/保留期，**无授权即不采**，禁止反爬绕过（AGENTS.md 已立规）。
- 统计合规：JPY canonical、median+分布、样本量与期限随指标展示、listing 与 closed 分离、`data_class` 强制声明（CLI 已强制）→ 落到 B3 统计服务与后台质检。
- 落点：P1 的来源登记→快照→质检管道；P4 的统计口径实现；对外免责声明随报告模板（已有）。
- **风险提示**：深度报告若含"投资/增值预测"式结论需持谨慎措辞（可写为初筛参考，非评估/法律/税务意见——JPPGSKILL 与报告模板已有此口径，保持）。

### 6.2 多币种收费（目标区：中国大陆、港澳台、新加坡、马来华人）
- **数据层**：金额一律服务端 canonical JPY 存储；币种=显示+结算属性；汇率带来源/日期/版本（AGENTS 已要求，禁硬编码）。
- **计费层**：定价（免费评估 0 / 深度报告 ¥）与订单表按 `currency + fx_rate + fx_date + payment_provider + status` 建模，迁移归 P1。
- **渠道现实（需产品决策，非纯技术）**：
  - iOS 内付费：应用内数字内容必须走 Apple IAP（JPY/CAD…按商店区）；Android/Google Play 同理 Play Billing。
  - 中国大陆安卓渠道：各自 SDK（支付宝/微信）或走渠道内购——需逐渠道适配。
  - 若想绕开商店抽成（网页/PWA/公众号下单）：属"虚拟服务"合规灰色带，需法律意见。
  - 建议第一版：海外与港澳台 = IAP；大陆 = 引导网页/微信支付 + 渠道 SDK 二选一，先不铺全。
- 落点：P1 数据模型、P2 B1 支付接入、P5 渠道扩展。**此项建议在 P2 开工前做一次产品决策（H 安排）**。

### 6.3 小象避坑 APP 上线与推广
- 上线：P2/P3 已含发布通道与合规清单。
- 推广建议（落 P3 上线后）：
  1. **内容获客为主**：小红书图文草稿流水线已存在且审核合规（聚合趋势、不复制房源图），做"日本买房避坑"选题矩阵，导流 APP。
  2. 华人圈社区/公众号/YouTube 短内容（港台新马买房话题）低成本测试。
  3. 与在日华人中介/行政书士/税理士合作导流（B 端订阅可反向成为 C 端渠道）。
  4. 免费评估作为钩子 → 深度报告付费的漏斗，数据埋点（P2 加）验证转化。
- 不在技术路线图内展开运营细节，P3 上线时出推广执行清单（H 可派一次性分析任务）。

---

## 7. Hermes 计划任务配置（cron，管家用）

建议创建（用户确认后生效，默认周一 09:00 CST，工作日提醒可选）：

| cron | 频率 | 内容 |
|---|---|---|
| 每周里程碑回顾 | 每周一 09:00 | 汇总各分支 diff/测试/门禁，对照本文档 P0–P5，输出"完成/进行/阻塞"与下周派单建议 |
| 里程碑出口检查 | P1–P4 出口日前 3 天 | 按 §4 出口清单逐项核验，未闭合项列给用户 |
| 数据管道健康（上线后） | 每日 09:00 | 后台调度器前日任务成功率/告警（P3 后启用） |

> cron 只做提醒与核验编排，不自动改代码；写代码一律由 Codex BOT 执行，杜绝两个 agent 同时改同一工作区。

## 7b. 工作时间窗与自主推进策略（2026-09-05 用户确认）

- **高峰静默**：周一至周五 09:00–18:00 **不执行任何 agent 任务**（避 API 高峰）。一切 cron 运行均落在窗口外（早 7:30 / 晚 20:30 / 周日 20:00 / 一次性提醒 20:00）。
- **闭环即推进**：每个任务经管家核验闭环后**立即**进入下一项，不再等待里程碑窗口；里程碑出口日期仅为验收锚点。
- **自主边界（夜间/周末无人值守）**：自主执行到 **commit + push** 为止；数据库写入/对象变更、部署、凭据/密钥、删除性操作、修改已应用 migration、改动冻结字段 = 一律先出确认清单等用户批准。晨/夜两班 cron（7:30 / 20:30）负责持续推进，含 git 状态防抖（进行中不叠加）。
- 白天的窗口留给需要用户在场的确认、演示与轻量动作。

---

## 8. 立即可执行清单（今天 → P0 结束）

1. [ ] 用户确认 §2 BOT 数量与 §3 方案 A/B（本文档同步最终版）
2. [ ] H 建 cron（§7，按确认项）
3. [ ] Codex（P0 会话）：JPPGSKILL git init + 远端推送（B4）
4. [ ] Codex（P0 会话）：陈旧 worktree 清理 + 仓库结构梳理文档（生成物边界表）
5. [ ] Codex（P0 会话）：migration baseline reconcile + staging 应用 + 备份恢复演练（H 复核，production 不动）
6. [ ] Codex（架构会话）：ADR-0001 收敛执行计划排期（P2 前置）

*红线重申：数据字段已冻结，任何 BOT 不得以"确认字段"为由反复返工；只允许 forward migration 与文档同步。*

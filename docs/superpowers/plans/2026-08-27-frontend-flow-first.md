# 前端完整流程优先实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先完成小象搜房／小象避坑第一版的可浏览、可操作前端闭环，逐屏让产品方确认后，再收敛数据结构、测试数据和完整测试。

**Architecture:** 保留现有静态 HTML + CSS + ES module 架构，不在本阶段引入新前端框架。已有真实 FastAPI/Supabase 接口继续使用；尚未完成的项目报告流程先使用明确标注的本地演示状态，不写入数据库、不伪装成真实市场数据。页面按公共查询、单项目分析、用户工作台、报告和账户五个边界组织，避免继续把所有状态塞进一个控制器。

**Tech Stack:** HTML、CSS、原生 JavaScript ES modules、现有 FastAPI/Supabase client、Playwright 仅用于阶段性浏览器检查。

**Spec:** `docs/superpowers/specs/2026-08-25-osaka-residential-analysis-design.md`

## Global Constraints

- 新单项目分析的权威路径保持为静态网页 → FastAPI → Supabase Auth/PostgreSQL/private Storage。
- 前端不得写入 `owner_user_id`、会员等级、权益、报告状态或任务状态。
- 演示资料必须标记为 `synthetic_fixture` 或“界面演示”，不得显示为真实市场事实。
- 本阶段不新增或修改数据库 migration，不应用线上 schema 变更。
- 真实用户数据、真实房源资料、service-role key 和数据库密码不得进入演示状态或仓库。
- 每个阶段只做最低限度的语法、启动和核心点击检查；所有完整测试、测试数据和数据库回归集中到 UI 确认之后。
- 保留现有用户修改和生成文件，不重置或清理无关工作区内容。

---

## 界面与流程清单

### 公共查询（`web/index.html`）

- 未登录：公开最近数据、登录/注册入口、查询控件禁用说明。
- 已登录：地区/房型/年月查询、查询历史、生成中进度、结果列表、详情返回。
- 空结果、后端不可用、生成失败、分页和公开数据来源说明。
- 新单项目入口：进入 `property-analysis.html`。

### 单项目分析（`web/property-analysis.html`）

- 选择用途与提交资料：文字/链接、文件选择、拖拽、文件错误、资料过期提示。
- 确认字段：已识别值、来源提示、用户修改、不知道/资料不足状态、完整度侧栏。
- 免费预览：六个完整度维度、购入费用项目、风险提醒、可比数据不足、注册保存。
- 登录后保存：未登录引导、转正中、已保存、重复点击幂等和失败恢复。
- 移动端菜单、键盘焦点、`390x844` 纵向流程。

### 用户工作台（`web/mypage.html`）

- 登录门槛、首次空状态、临时/已保存项目列表。
- 项目状态：待确认、待启动、生成中、已完成、失败可重试、更新次数已用尽。
- 项目详情入口、启动完整分析、补充资料、生成报告、版本切换。

### 报告与版本

- 免费预览详情、完整报告锁定态、权益可用态、生成中、失败和完成态。
- 完整报告章节：结论、基本信息、来源可信度、市场比较、购入/持有成本、自住、投资、法律清单、避坑、资料缺口、版本/免责声明。
- 四级行动结论必须与关键风险并列展示，不能用一个综合分数掩盖风险。
- 报告版本列表、旧版本只读、一次补充资料更新入口。

### 账户（`web/profile.html` 与共用账户面板）

- 登录、注册、密码错误、重复账号、登录过期和登出。
- 找回密码入口/状态、修改密码、资料编辑、删除账户确认和隐私/条款同意状态。
- 会员等级和额度只读展示，不能在前端编辑。

---

## 实施任务

### Task 1: 锁定界面状态矩阵与视觉参考

**Files:**
- Create: `docs/superpowers/plans/2026-08-27-frontend-flow-first.md`
- Reference: `docs/superpowers/specs/2026-08-25-osaka-residential-analysis-design.md`
- Reference: `web/index.html`, `web/mypage.html`, `web/profile.html`, `web/property-analysis.html`, `web/styles.css`, `web/property-analysis.css`

- [x] 盘点现有入口、共享账户面板、单项目流程和缺失的报告/版本状态。
- [ ] 生成公共查询、单项目分析、工作台/报告、账户四组协调视觉概念，并保留真实页面文字在代码中渲染。
- [ ] 从确认后的视觉方向提取颜色、字体、间距、按钮、表单、状态、表格和移动端规则，记录到实现文件头部注释或共享 token 区域。
- [ ] 让产品方确认“界面范围、状态矩阵和视觉方向”后再开始大规模页面实现。

### Task 2: 整理共用应用壳与账户状态

**Files:**
- Modify: `web/styles.css`
- Modify: `web/app.js`
- Modify: `web/index.html`
- Modify: `web/mypage.html`
- Modify: `web/profile.html`

- [ ] 抽取共用 topbar、账户面板、登录/注册表单、消息、加载、空状态和错误状态的统一样式与 DOM 约定。
- [ ] 保留现有 Supabase 登录路径，补齐找回密码、登录过期、登出后回到当前页和统一错误文案的界面状态；未接通的后端动作显示明确的待接入状态。
- [ ] 将会员等级、每日额度、项目数等信息设为只读展示，并移除会尝试提交服务端管理字段的前端写入。
- [ ] 仅做 HTML/JS 语法检查和本地静态页面启动检查。

### Task 3: 完成单项目分析的所有前端状态

**Files:**
- Modify: `web/property-analysis.html`
- Modify: `web/property-analysis.css`
- Modify: `web/js/property-intake.js`
- Modify: `web/js/api-client.js`

- [ ] 把提交、确认、预览、保存五个阶段变成可重复进入的明确界面状态，并统一返回、重试、过期和取消动作。
- [ ] 为字段增加“已识别/用户确认/资料不足/冲突/不适用”的可视状态和来源占位区域；不改变现有后端字段含义。
- [ ] 让文件列表展示文件名、大小、类型错误和移除操作；上传失败时保留用户输入并提供重试。
- [ ] 让免费预览完整展示六个资料完整度维度、费用项目、风险数量、可比数据状态和三个优先补充事项。
- [ ] 增加登录保存后的工作台跳转、已保存确认和恢复入口；所有未接通完整报告动作使用显式演示态。
- [ ] 只运行 `node --check`、Python 静态服务和一次核心点击冒烟，不执行数据库回归。

### Task 4: 完成工作台、项目详情和报告版本界面

**Files:**
- Modify: `web/mypage.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Create: `web/project.html`
- Create: `web/js/project-workspace.js`
- Create: `web/project-workspace.css`

- [ ] 在工作台增加项目状态时间线、资料完整度摘要、权益/额度只读区和主要下一步动作。
- [ ] 创建项目详情界面，覆盖免费预览、完整报告锁定、完整分析生成中、完成、失败重试、补充资料和版本列表。
- [ ] 创建完整报告阅读界面，覆盖四级行动结论、证据/来源、市场可比限制、成本/收益假设、法律检查状态、风险动作和免责声明。
- [ ] 使用固定的界面演示 fixture，字段包含 `data_class: synthetic_fixture`，并在页面显著标记“界面演示，不代表真实结论”。
- [ ] 实现页面内本地状态切换，确保按钮、返回、重试、版本查看和补充资料入口不是静态装饰。
- [ ] 完成桌面和 `390x844` 的浏览器检查后暂停，等待产品方逐屏确认。

### Task 5: 补齐账户安全和资料流程

**Files:**
- Modify: `web/profile.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`

- [ ] 增加找回密码请求、邮件已发送、链接过期和回到登录状态的界面。
- [ ] 增加修改密码、登出所有会话、删除账户确认和删除完成/失败状态；后端未接通时禁止伪造成功。
- [ ] 增加隐私政策/服务条款同意版本与更新时间的只读展示位置。
- [ ] 核对所有输入的可见 `label`、键盘顺序、焦点样式、`aria-live` 消息和移动端触控尺寸。

### Task 6: UI 评审包与一次性数据契约评审

**Files:**
- Modify: `progress.md`
- Modify: `docs/data-dictionary.md`
- Modify: `docs/superpowers/specs/2026-08-25-osaka-residential-analysis-design.md` only when product decisions change
- Create: `docs/superpowers/ui-review/2026-08-27-screen-flow-review.md`

- [ ] 为每个页面记录入口、前置条件、可点击动作、成功态、失败态、返回路径和待产品确认项。
- [ ] 收集产品方逐屏反馈，只修改确认后的 UI，不在数据层先行扩展。
- [ ] 根据确认后的字段和报告章节反查 FastAPI request/response、Supabase 表和 migration，列出必要新增/删除/改名字段及其 provenance/data class。
- [ ] 给出 forward migration、回滚/forward-fix、备份/恢复和权限验证方案；未经确认不应用线上数据库。

### Task 7: 测试数据与集中验证

**Files:**
- Create/Modify: `tests/fixtures/` only after the UI contract is approved
- Modify: focused tests adjacent to the final contracts
- Modify: `progress.md`

- [ ] 创建仅含 `synthetic_fixture` 的匿名、已保存、生成中、失败、完整报告和历史版本数据。
- [ ] 集中执行 Python、前端、浏览器、SQL/RLS 和 API 回归，分别记录真实执行命令与未覆盖项。
- [ ] 运行 `git diff --check`、构建/语法检查、桌面与 `390x844` 浏览器检查；对视觉概念和最新截图做一次最终对照。
- [ ] 只有在所有必要流程和测试证据齐全后，才评估是否可以进入 staging migration/deploy。

---

## 阶段门槛

1. **UI 结构门槛：** 所有清单界面可进入，核心按钮有响应，失败/空/加载/过期状态可恢复。
2. **产品确认门槛：** 产品方逐屏确认页面层级、字段、动作名称和报告章节；未确认项不得反向驱动数据库设计。
3. **数据契约门槛：** 字段、来源证据、数据类别、版本和所有权边界完成一次性审查。
4. **验证门槛：** 测试数据和集中回归通过，且明确列出未验证的真实服务、真实账号和线上部署风险。

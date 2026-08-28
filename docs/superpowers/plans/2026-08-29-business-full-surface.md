# 小象数据完整 B 端页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 补齐小象数据 B 端 6 个缺失的业务页面，并提供可评审、可切换三语、明确标记为本地演示的交互流程。

**Architecture:** 保留现有静态 HTML 架构和 `business.css` 视觉系统。新增页面共用 `business-pages.css` 与 `business-pages.js`，动态演示数据只存在浏览器内存，不调用 API；核心页面仍由既有 `app.js` 管理。

**Tech Stack:** HTML、CSS、原生 JavaScript、现有 `ZouI18n`、Playwright Chromium。

**Spec:** `docs/superpowers/specs/2026-08-29-business-full-surface-design.md`

## Global Constraints

- 新页面必须标明 `synthetic_fixture` 或“仅本地演示”。
- 不新增数据库表、迁移、RLS、Auth、支付或真实会员写入。
- 日本房产相关界面统一使用“物件”，数据来源名称保留原语言。
- 支持 `zh-CN`、`en`、`ja`，且语言切换不离开当前页面。
- 桌面验证 `1440x900`，移动验证 `390x844`，页面不能产生横向溢出。
- 所有控件使用语义 HTML、可见标签和 `:focus-visible`。

---

### Task 1: 共用页面样式、字典和本地演示控制器

**Files:**
- Create: `web/business-pages.css`
- Create: `web/js/business-pages.js`
- Modify: `web/js/i18n.js`

**Interfaces:**
- `business-pages.js` 根据 `body[data-business-page]` 分发到 `organization`、`billing`、`usage`、`subscriptions`、`exports`、`service-tasks` 渲染器。
- 动态文本通过 `window.ZouI18n.t(key, fallback)` 读取，状态操作只更新内存夹具和可见提示。

- [ ] **Step 1: Write the failing browser assertions**

在 `tests/web/business-home-members-locale.spec.js` 增加 6 个新路由的可见性和核心交互断言；先运行该文件，确认新路由尚不存在或核心选择器不存在时失败。

Run: `npx playwright test tests/web/business-home-members-locale.spec.js --project=chromium`

- [ ] **Step 2: Add shared translations and style primitives**

在 `web/js/i18n.js` 增加 6 个页面标题、页面标题/说明、演示提示、按钮和状态键；在 `web/business-pages.css` 增加紧凑工作区、状态卡、表格、进度条、筛选栏、任务卡和移动端规则。

- [ ] **Step 3: Implement the local controller**

实现 `business-pages.js` 的 HTML 转义、通用提示、页面分发、各页固定 `synthetic_fixture` 数据和本地状态切换；不得引入 `fetch`、Supabase 写入或支付调用。

- [ ] **Step 4: Run syntax checks**

Run: `node --check web/js/business-pages.js && node --check web/js/i18n.js && git diff --check`

Expected: 命令成功退出。

### Task 2: 机构、套餐账单和用量页面

**Files:**
- Create: `web/organization.html`
- Create: `web/billing.html`
- Create: `web/usage.html`
- Modify: `web/ui-review.html`

**Interfaces:**
- 页面通过 `data-business-page` 调用共用控制器。
- 机构页使用 `#organizationMembers`、`#organizationNotice`。
- 账单页使用 `#billingCurrency`、`#billingNotice`、`#autoRenewButton`。
- 用量页使用 `#usageList`、`#usageFilter`、`#usageNotice`。

- [ ] **Step 1: Build the shared B shell in each page**

复用现有 B 端品牌、导航、语言选择器和 `business.css`，为页面标题、主标题、说明、演示标签添加 `data-i18n` 属性；不加载 `app.js`，避免依赖旧查询 DOM。

- [ ] **Step 2: Add organization interactions**

显示 4 个演示成员和 5 个席位上限；“邀请成员”按钮只在 `#organizationNotice` 显示本地演示提示，“查看”按钮更新右侧详情文本。

- [ ] **Step 3: Add billing interactions**

显示 B Free 与 B Data Pro 套餐、CNY/JPY/USD 预置价格、下次续费和账单记录；币种选择更新价格文本，自动续费按钮只切换“开启/已关闭（演示）”。

- [ ] **Step 4: Add usage interactions**

显示查询、统计、订阅、导出四类机构共享用量；筛选器只切换本地事件列表，并展示重置时间和“服务端计量”说明。

### Task 3: 统计订阅、导出和服务任务池页面

**Files:**
- Create: `web/subscriptions.html`
- Create: `web/exports.html`
- Create: `web/service-tasks.html`
- Modify: `web/ui-review.html`

**Interfaces:**
- 订阅页使用 `#subscriptionForm`、`#subscriptionList`、`#subscriptionNotice`。
- 导出页使用 `#exportForm`、`#exportList`、`#exportNotice`。
- 任务页使用 `#taskFilter`、`#taskList`、`#taskNotice`。

- [ ] **Step 1: Build the three page shells**

使用同一导航和页面容器；订阅页提供条件组合表单，导出页提供数据集/格式/行数表单，任务页提供状态筛选和不含个人联系方式的任务卡。

- [ ] **Step 2: Add subscription state operations**

为固定演示订阅实现暂停/恢复、删除和添加；每次操作更新列表和本地提示，不触发网络请求。

- [ ] **Step 3: Add export state operations**

创建演示任务后追加 `queued` 记录；完成的固定记录只显示“查看演示”，不生成或下载真实数据。

- [ ] **Step 4: Add task pool operations**

实现状态筛选、查看任务详情、申请和撤回；任务内容只包含概略地区、物件类型、服务类型和时间，不包含邮箱、电话、精确地址或附件。

### Task 4: 回归测试、评审入口和文档

**Files:**
- Modify: `tests/web/business-home-members-locale.spec.js`
- Modify: `progress.md`

- [ ] **Step 1: Complete focused Playwright coverage**

覆盖 6 个新路由、桌面/移动无溢出、三语切换、机构邀请、账单币种/续费、用量筛选、订阅暂停、导出创建和任务申请/撤回。

Run: `npx playwright test tests/web/business-home-members-locale.spec.js --project=chromium`

- [ ] **Step 2: Run the full Web suite**

Run: `npm run test:web`

Expected: 所有现有与新增用例通过。

- [ ] **Step 3: Run final static checks**

Run: `node --check web/js/business-pages.js && node --check web/js/i18n.js && git diff --check`

- [ ] **Step 4: Update progress**

记录 6 个路由、演示边界、三语支持和确切测试结果；明确真实数据库/权限/支付仍待后续架构批准。

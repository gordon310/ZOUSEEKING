# 小象数据首页、会员管理与三语界面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精简小象数据 B 端主页，把查询迁移到独立页面，增加管理员会员管理演示，并让三个 B 端功能界面共享中文、英文、日文切换。

**Architecture:** 保留现有静态 HTML + CSS + 原生 JavaScript 结构。首页只负责账户入口、欢迎信息和无图片的最近更新；新 `data-query.html` 复制现有 B 端壳并承接查询 DOM 契约，让已有 `app.js` 查询逻辑保持单一路径。新增一个轻量 `i18n.js` 负责静态文本和动态文案的 locale 选择；管理员会员管理仅使用页面内 `synthetic_fixture`，不扩展数据库或认证权限。

**Tech Stack:** HTML、CSS、原生 JavaScript、现有 Supabase/FastAPI client、现有 Playwright 浏览器检查。

**Spec:** `docs/superpowers/specs/2026-08-28-business-home-members-locale-design.md`

## Global Constraints

- 只修改静态界面和本地演示交互，不执行真实会员写入、数据库 migration、RLS 修改或认证策略修改。
- 现有 `app.js` 查询、认证、分析和工作台逻辑继续使用原有 ID 契约；没有对应 DOM 时必须安全退出，不能在主页报错。
- `data/content_library.json` 和 `web/content-library.json` 由生成流程维护，不手工编辑；展示层不把演示数据伪装成实时市场事实。
- 所有页面保持可见 label、`:focus-visible`、键盘操作、`aria-live` 状态、`390x844` 无横向溢出和手机输入框至少 `16px`。
- 不新增依赖，不重置或清理工作区中与本任务无关的已有修改。

---

### Task 1: 建立共享三语基础和页面壳标记

**Files:**
- Create: `web/js/i18n.js`
- Modify: `web/index.html`
- Modify: `web/analysis.html`
- Modify: `web/mypage.html`
- Modify: `web/profile.html`
- Modify: `web/admin.html`

**Interfaces:**
- Produces `window.ZouI18n.t(key, fallback)`, `window.ZouI18n.apply(root)`, `window.ZouI18n.locale()` and `window.ZouI18n.setLocale(locale)` for page scripts.
- Consumes `data-i18n`, `data-i18n-placeholder`, `data-i18n-aria-label` and `data-i18n-title` attributes added to page markup.

- [ ] **Step 1: Add the failing static contract check**

Add a focused Node assertion script only if the repository already has a browser-test helper; otherwise use the existing syntax command as the first check. The contract to verify after implementation is:

```bash
node --check web/js/i18n.js
node --check web/app.js
```

Expected before implementation: `web/js/i18n.js` does not exist, so the check fails.

- [ ] **Step 2: Implement the minimal locale service**

Create `web/js/i18n.js` with the exact public shape below. The dictionary must contain the visible shell and main-screen keys used by the three B pages, including `brand.business`, `nav.query`, `nav.analysis`, `nav.workspace`, `nav.profile`, `account.email`, `account.password`, `account.login`, `account.register`, `account.forgot`, `query.title`, `analysis.title`, `workspace.title`, and `latest.title` in `zh-CN`, `en`, and `ja`.

```js
window.ZouI18n = {
  t(key, fallback = ""),
  apply(root = document),
  locale(),
  setLocale(locale)
};
```

`setLocale` accepts only `zh-CN`, `en`, or `ja`, stores `zou_ui_locale`, and reloads the current page. `apply` updates element text with `textContent`, placeholder/aria/title attributes, and `document.documentElement.lang`; it must never use untrusted `innerHTML`.

- [ ] **Step 3: Mark shared shell text and add language selectors**

Add the same native select to the B topbars and admin header:

```html
<label class="locale-switcher">
  <span class="visually-hidden" data-i18n="locale.label">界面语言</span>
  <select data-locale-switcher aria-label="界面语言">
    <option value="zh-CN">中文</option>
    <option value="en">English</option>
    <option value="ja">日本語</option>
  </select>
</label>
```

Wrap label text that currently shares a `<label>` with an input in a `<span data-i18n="...">` so applying translations cannot remove the input. Load `i18n.js` before `app.js` and `admin.js` on every modified page.

- [ ] **Step 4: Run the syntax and markup smoke check**

Run:

```bash
node --check web/js/i18n.js
node --check web/app.js
node --check web/js/admin.js
git diff --check
```

Expected: all commands exit `0`; no database or network action is performed.

### Task 2: 精简 B 端主页并迁移查询入口

**Files:**
- Modify: `web/index.html`
- Create: `web/data-query.html`
- Modify: `web/app.js`
- Modify: `web/business.css`
- Modify: `web/business.js`
- Modify: `web/analysis.html`
- Modify: `web/mypage.html`
- Modify: `web/profile.html`
- Modify: `web/ui-review.html`

**Interfaces:**
- `data-query.html` produces the existing query DOM IDs: `queryPanel`, `queryForm`, `prefectureSelect`, `citySelect`, `wardSelect`, `assetTypeSelect`, `yearSelect`, `monthSelect`, `queryButton`, `queryHint`, `queryHistory`, `historyList`, `latestPanel`, `latestList`, `latestTitle`, `pagination`, `prevPage`, `pageInfo`, `nextPage`, `detailPage`, `detailContent`, and `backToList`.
- `app.js` consumes those IDs when present and skips optional query/history/detail work when they are absent on `index.html`.

- [ ] **Step 1: Record the homepage acceptance assertions**

The final browser check must assert that the homepage has no `#queryPanel`, no `.business-overview`, no `.service-task-panel`, and that the visible `.latest-panel` contains no `img` elements. The dedicated query page must contain `#queryForm` and all query IDs listed above.

- [ ] **Step 2: Remove the query/overview/service blocks from the homepage**

Keep the topbar, account panel, a short hero, latest panel, detail/dialog infrastructure, and existing script order. Change the B data navigation from `index.html` to `data-query.html` on every B page and on the role review page. Put the latest section immediately after the account section in the HTML so mobile order is account → recent updates → welcome.

- [ ] **Step 3: Create the dedicated query page**

Copy the existing B shell from `index.html` into `web/data-query.html`, retain the account panel and hero copy for the query task, and place the original query form/history/latest/detail markup below it. Add `data-i18n` markers to the title, form labels, query button, hint, pagination, and detail return button. Load `config.js`, `i18n.js`, `app.js`, and `business.js` in that order.

- [ ] **Step 4: Make the shared controller safe on the sparse homepage**

Guard any direct query element access in `renderQueryOptions`, `populateCities`, `populateWards`, pagination bindings, and query-history rendering. `renderView` must continue to hide/show optional `query-panel`, `latest-panel`, `detail-page`, `analysis-panel`, and `mypage-panel` without throwing when a page omits one of them.

- [ ] **Step 5: Render compact image-free recent rows**

Change `renderLatest()` to render this structure for each record:

```html
<article class="latest-card" data-detail="...">
  <span class="latest-currency" aria-hidden="true">¥</span>
  <div>
    <h3>记录名称</h3>
    <p class="latest-record-meta">月份 · 地区</p>
  </div>
</article>
```

Keep the title passed through `displayPropertyText` and `escapeHtml`; keep the existing click/Enter/Space detail behavior for logged-in users. Do not render `record.images` on any latest row.

- [ ] **Step 6: Add homepage-specific compact layout rules**

Use a `business-home` body class. On desktop, put the account panel in column 1, the latest panel directly under it in column 1, and the compact hero in column 2. On mobile, use one column and keep the latest panel immediately after the account panel. Reduce latest padding and typography while preserving a visible focus state and at least `24px` row height.

- [ ] **Step 7: Run the first route smoke check**

Run:

```bash
node --check web/app.js
node --check web/js/business.js
git diff --check
```

Then load `/index.html` and `/data-query.html` through the existing static server and verify no page error occurs before moving to the admin changes.

### Task 3: Add synthetic member management to the admin console

**Files:**
- Modify: `web/admin.html`
- Modify: `web/admin.css`
- Modify: `web/js/admin.js`

**Interfaces:**
- `admin.html` produces a `data-admin-tab="members"` tab, a `data-admin-section` containing `members`, `#memberSearch`, `#memberStatusFilter`, `#memberList`, and `#memberNotice`.
- `admin.js` owns the local `memberRows` fixture and only mutates DOM/local state; no API client or database call is added.

- [ ] **Step 1: Add the member fixture and filtering contract**

Define four non-sensitive local rows with fields `id`, `label`, `tier`, `status`, `quota`, `activity`, and `detail`, all inside `web/js/admin.js`. Use a visible `synthetic_fixture` note in the section. Search must match `label`, `id`, or `tier`; status filtering must match `all`, `active`, `paused`, or `review`.

- [ ] **Step 2: Add the member-management tab and table**

Add a tab labeled “会员管理” and a compact table with columns “会员”, “等级”, “状态”, “额度使用”, “最近活动”, “操作”. Use a `<caption>`, row headers, native buttons, and a visible empty state when filters match nothing. Add a detail aside action that reuses `#adminDetail` and announces local-only changes through `#memberNotice`/`#adminNotice`.

- [ ] **Step 3: Implement local search, status filtering, view, and pause/resume**

Implement `renderMembers()`, `memberMatches(row)`, and `toggleMemberStatus(id)` in `admin.js`. `renderMembers()` must use DOM construction or escaped text for fixture values. “查看” writes the selected row’s non-sensitive detail into the existing detail panel. “暂停（演示）” and “恢复（演示）” change only the local row status and button text, then reapply filters.

- [ ] **Step 4: Add dense responsive CSS**

Extend the existing admin table styles for the member table, search controls, status text, empty state, and mobile horizontal scrolling only inside the table wrapper. Keep the admin page itself free of horizontal overflow and keep buttons keyboard reachable.

- [ ] **Step 5: Run admin syntax checks**

Run:

```bash
node --check web/js/admin.js
git diff --check
```

Expected: the members tab changes visible local state and never makes a network request.

### Task 4: Localize the three B-end function screens and finish review links

**Files:**
- Modify: `web/data-query.html`
- Modify: `web/analysis.html`
- Modify: `web/mypage.html`
- Modify: `web/profile.html`
- Modify: `web/app.js`
- Modify: `web/js/business.js`
- Modify: `web/ui-review.html`
- Modify: `web/styles.css`
- Modify: `web/business.css`
- Modify: `web/admin.html`

**Interfaces:**
- The three B screens consume `window.ZouI18n.t()` for page-specific dynamic headings/hints and use `data-i18n` for static chrome.
- The review entry produces links to `data-query.html`, `analysis.html`, `mypage.html`, and `profile.html` with the agreed B role descriptions.

- [ ] **Step 1: Mark all visible functional-screen chrome**

Add translation keys to the query page’s form labels/buttons/hints, analysis page’s title/form labels/compare controls, and workbench page’s title/empty/status/action labels. Add localized labels to the B navigation and account panel in each page. Keep raw Japanese prefecture/city names and local fixture record content unchanged.

- [ ] **Step 2: Route dynamic strings through the locale service**

Use a helper in `app.js` with the behavior below for strings rendered after login/query state changes:

```js
function uiText(key, fallback) {
  return window.ZouI18n?.t(key, fallback) || fallback;
}
```

Apply it to the latest heading state, query hints, pagination labels, empty/error messages, analysis hints, and workbench empty/loading/status messages. Keep `escapeHtml` around values inserted into HTML.

- [ ] **Step 3: Make locale switching stable across routes**

When the selector changes on `data-query.html`, `analysis.html`, or `mypage.html`, store the locale and reload the same URL. After reload, the selector must retain the selected value and `document.documentElement.lang` must be `zh-CN`, `en`, or `ja` accordingly.

- [ ] **Step 4: Update the role review entry**

Change the B “数据查询入口” review link and all B navigation references to `data-query.html`. Add an admin review link for `admin.html?demo=1#members`, preserving the review page’s explanation that member rows are synthetic and no real data is changed.

- [ ] **Step 5: Run static checks**

Run:

```bash
for file in web/js/*.js; do node --check "$file" || exit 1; done
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src
git diff --check
```

Expected: all JavaScript files parse, Python compilation remains clean, and no generated content library is modified.

### Task 5: Browser verification and documentation handoff

**Files:**
- Modify: `progress.md`
- Modify: `docs/superpowers/ui-review/2026-08-28-role-surface-review.md` only if its B navigation map is stale
- Create: `tests/web/business-home-members-locale.spec.js` only if the existing Playwright test setup can run without adding dependencies

- [ ] **Step 1: Start from the already-running static preview**

Use the existing `python3 -m http.server 8787 -d web` process if it is still serving port 8787. Do not start a duplicate server or alter production/staging services.

- [ ] **Step 2: Verify desktop homepage and query separation**

At `1440x900`, visit `/index.html` and `/data-query.html`. Check:

```text
index: query panel absent; overview absent; service queue absent; latest list has no img; latest list is below account.
data-query: query form visible; selecting conditions and submitting updates local result state; detail opens only when logged in/demo state permits; back returns to list.
```

- [ ] **Step 3: Verify the three locales**

For `/data-query.html`, `/analysis.html`, and `/mypage.html`, select `中文`, `English`, and `日本語`; reload each page; assert the selected value persists, `document.documentElement.lang` changes, and the page title/nav/main heading are translated. Verify no console page errors.

- [ ] **Step 4: Verify admin members workflow**

At desktop and `390x844`, open `admin.html?demo=1#members`, filter by search and status, view a member, pause it, restore it, and confirm the notice says the change is local/demo only. Check that the page has no horizontal overflow.

- [ ] **Step 5: Capture the required visual QA evidence**

Use the existing accepted design/reference screenshots from the prior B-end review and capture fresh implementation screenshots for the sparse homepage, query page, and admin members view. Inspect the accepted reference and each fresh screenshot with `view_image`; compare at least these five points: homepage density, account/latest order, no-image row anatomy, desktop/mobile typography and controls, and admin table density. Remove temporary screenshots after inspection unless they are required in the review record.

- [ ] **Step 6: Update progress with exact evidence**

Record changed routes, browser viewport sizes, locale workflow, admin member workflow, syntax commands, and any remaining intentional deviations in `progress.md`. State explicitly that member management remains synthetic and no DB/RLS/auth changes were made.

- [ ] **Step 7: Run the final scoped checks**

Run:

```bash
for file in web/js/*.js; do node --check "$file" || exit 1; done
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src
git diff --check
```

Report browser checks separately from syntax checks; do not claim a full automated suite unless an actual test command was executed and passed.

## Self-review checklist

- Homepage has no independent query entry and no image in latest rows.
- Query functionality still has every DOM ID expected by `app.js` on its dedicated route.
- Member management is visibly synthetic and cannot write to a backend.
- Chinese, English, and Japanese cover the three requested B-end interfaces without translating source data falsely.
- Desktop B/admin layouts remain compact while mobile keeps usable controls and no page-level overflow.
- No migration, RLS, authentication, generated-library, or unrelated source changes are included.

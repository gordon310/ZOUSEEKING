const { test, expect } = require("@playwright/test");
const path = require("node:path");

const demoSession = { username: "Demo User", email: "demo@example.com", provider: "demo" };

// 匿名/免费首页的"最近更新"面板按授权内容库渲染,上限为匿名 pageSize(5)。
// 未授权条目下架后(D6a)面板会按剩余授权条数缩短,因此期望值必须由库本身推导,不能写死 5。
const library = require("../../data/content_library.json");
const latestCardCount = Math.min(5, library.length);

test.beforeEach(async ({ page }) => {
  await page.route("**/content-library.json", async (route) => {
    await route.fulfill({
      path: path.resolve(__dirname, "../../data/content_library.json"),
      contentType: "application/json",
    });
  });
});

async function seedSession(page, locale = "zh-CN") {
  await page.addInitScript(({ session, locale: initialLocale }) => {
    localStorage.setItem("zou_house_session", JSON.stringify(session));
    localStorage.setItem("zou_ui_locale", initialLocale);
  }, { session: demoSession, locale });
}

async function seedBusinessReleaseScope(page) {
  await page.addInitScript(() => {
    window.ZOUSEEKING_RELEASE_SCOPE = Object.freeze({
      phase: "consumer_intake_preview",
      businessOperations: true,
      adminOperations: false,
    });
  });
}

async function waitForOrganizationLoad(page, action, { meStatus, membersStatus, membersCount, waitForMembers = true } = {}) {
  const responseFor = (pathname) => page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === pathname;
  });
  const meResponse = responseFor("/api/org/me");
  const membersResponse = waitForMembers ? responseFor("/api/org/members") : null;
  const [, organizationResponse, membersListResponse] = await Promise.all([action(), meResponse, membersResponse]);

  expect(organizationResponse.status()).toBe(meStatus);
  if (membersListResponse) {
    expect(membersListResponse.status()).toBe(membersStatus);
    const payload = await membersListResponse.json();
    expect(Array.isArray(payload.members)).toBe(true);
    if (membersCount !== undefined) expect(payload.members).toHaveLength(membersCount);
  }
}

test("B 端主页保持精简并展示无图片的日元最近更新", async ({ page }) => {
  expect(latestCardCount).toBeGreaterThan(0);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/index.html");
  await expect(page.locator("body.auth-ready")).toBeVisible();

  await expect(page.locator("#queryPanel")).toHaveCount(0);
  await expect(page.locator(".business-overview")).toHaveCount(0);
  await expect(page.locator(".service-task-panel")).toHaveCount(0);
  await expect(page.locator(".business-latest-panel .latest-card")).toHaveCount(latestCardCount);
  await expect(page.locator(".business-latest-panel .latest-card img")).toHaveCount(0);
  await expect(page.locator(".business-latest-panel .latest-currency")).toHaveText(Array(latestCardCount).fill("¥"));
  await expect(page.getByRole("link", { name: "数据查询" }).first()).toHaveAttribute("href", "data-query.html");

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("B 端最近更新面板对匿名访问最多显示 5 条", async ({ page }) => {
  // 合成 fixture(非市场数据):库扩容/新增授权条目后,匿名首页仍必须被 pageSize 截断到 5。
  const expanded = Array.from({ length: 7 }, (_, index) => ({
    ...library[index % library.length],
    id: `synthetic_fixture_${index}`,
    title: `合成条目 ${index}`,
  }));
  await page.route("**/content-library.json", (route) =>
    route.fulfill({ body: JSON.stringify(expanded), contentType: "application/json" }),
  );

  await page.goto("/index.html");
  await expect(page.locator("body.auth-ready")).toBeVisible();
  await expect(page.locator(".business-latest-panel .latest-card")).toHaveCount(5);
  await expect(page.locator(".business-latest-panel .latest-card h3").first()).toHaveText("合成条目 0");
});

test("B 端查询页承接查询入口并支持记录详情返回", async ({ page }) => {
  await seedSession(page);
  await page.goto("/data-query.html");
  await expect(page.locator("body.auth-ready")).toBeVisible();
  await expect(page.locator("#queryForm")).toBeVisible();
  await expect(page.locator("#queryForm select")).toHaveCount(6);
  await expect(page.locator(".latest-card").first()).toBeVisible();

  await page.locator(".latest-card").first().click();
  await expect(page.locator("#detailPage")).toBeVisible();
  await page.locator("#backToList").click();
  await expect(page.locator("#detailPage")).toBeHidden();
  await expect(page.locator("#latestList")).toBeVisible();
});

test("B 端三语界面切换会保留在当前功能页", async ({ page }) => {
  await page.goto("/data-query.html");
  await expect(page.locator("body.auth-ready")).toBeVisible();

  await page.locator("[data-locale-switcher]").selectOption("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("h1").first()).toHaveText("Public data query");

  await page.locator("[data-locale-switcher]").selectOption("ja");
  await expect(page.locator("html")).toHaveAttribute("lang", "ja");
  await expect(page.locator("h1").first()).toHaveText("公開データ検索");
});

test("管理员会员管理仅操作本地演示记录", async ({ page }) => {
  await page.goto("/admin.html?demo=1#members");
  await expect(page.locator("#members")).toBeVisible();
  await expect(page.locator("#memberList tr[data-member-row]")).toHaveCount(4);

  await page.locator("#memberSearch").fill("MBR-003");
  await expect(page.locator("#memberList tr[data-member-row]")).toHaveCount(1);
  await page.locator("[data-member-action='view']").click();
  await expect(page.locator("#memberNotice")).toContainText("演示详情");
  await page.locator("[data-member-action='toggle']").click();
  await expect(page.locator("#memberList .admin-table-status")).toHaveText("正常");
  await expect(page.locator("#memberNotice")).toContainText("没有修改真实会员资料");
  await page.locator("[data-member-action='toggle']").click();
  await expect(page.locator("#memberList .admin-table-status")).toHaveText("已暂停");
});

test("小象数据六个补齐页面都提供可评审入口", async ({ page }) => {
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(`console: ${message.text()}`);
  });
  const pages = [
    ["organization.html", "机构与成员"],
    ["billing.html", "套餐与账单"],
    ["usage.html", "用量与额度"],
    ["subscriptions.html", "统计订阅"],
    ["exports.html", "数据导出"],
    ["service-tasks.html", "服务任务池"],
  ];

  for (const [route, heading] of pages) {
    await page.goto(`/${route}`);
    await expect(page.locator("body.business-page-ready")).toBeVisible();
    await expect(page.locator("h1")).toHaveText(heading);
    if (route !== "exports.html" && route !== "organization.html" && route !== "service-tasks.html") {
      const demoLabel = page.locator(".business-demo-label, .business-fixture-note").first();
      await expect(demoLabel).toContainText("界面演示");
      await expect(demoLabel).toContainText("合成示例数据");
      await expect(page.locator("body")).not.toContainText("synthetic_fixture");
    } else if (route === "exports.html") {
      await expect(page.locator(".business-fixture-note").first()).toContainText("真实数据");
    } else {
      await expect(page.locator(".business-demo-label, .business-fixture-note")).toHaveCount(0);
      await expect(page.locator("body")).not.toContainText("synthetic_fixture");
    }
    await expect(page.locator("[data-locale-switcher]")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);

    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.setViewportSize({ width: 1440, height: 900 });
  }

  expect(browserErrors).toEqual([]);
});

test("机构页读取真实数据并诚实呈现空态和失败态", async ({ page }) => {
  const requests = [];
  const consoleMessages = [];
  const pageErrors = [];
  page.on("request", (request) => requests.push(`${request.method()} ${request.url()}`));
  page.on("console", (message) => consoleMessages.push(`${message.type()}: ${message.text()}`));
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await seedBusinessReleaseScope(page);
    await page.addInitScript(() => { window.ZOUSEEKING_API_BASE_URL = window.location.origin; });
    await page.route(/\/api\/org\/me(?:\?.*)?$/, (route) => route.fulfill({ json: {
      organization: { name: "大阪数据协作社" }, role: "owner", seats: { used: 2, limit: 5 },
      plan: { name: "B Data Pro", entitlements: { queries: { used: 3, limit: 500, period: "month" } } },
    } }));
    await page.route(/\/api\/org\/members(?:\?.*)?$/, (route) => route.fulfill({ json: { members: [
      { display_name: "h***@example.com", role: "owner", status: "active", joined_at: "2026-09-01T00:00:00+00:00" },
      { display_name: "成员 2", role: "member", status: "active", joined_at: "2026-09-02T00:00:00+00:00" },
    ] } }));
    await page.route(/\/api\/org\/invitations(?:\?.*)?$/, (route) => route.fulfill({ json: { invitations: [] } }));
    await waitForOrganizationLoad(page, () => page.goto("/organization.html"), { meStatus: 200, membersStatus: 200, membersCount: 2 });
    await expect(page.locator("#organizationAccountHeading")).toHaveText("大阪数据协作社");
    await expect(page.locator("#businessSeatSummary")).toHaveText("已使用 2 / 5 个席位");
    await expect(page.locator("#organizationMembers [data-member-row]")).toHaveCount(2);
    await expect(page.locator("#organizationNotice")).toContainText("真实成员");
    await expect(page.locator("body")).not.toContainText("尚未加入机构");

    await page.unroute(/\/api\/org\/members(?:\?.*)?$/);
    await page.route(/\/api\/org\/members(?:\?.*)?$/, (route) => route.fulfill({ json: { members: [] } }));
    await waitForOrganizationLoad(page, () => page.reload(), { meStatus: 200, membersStatus: 200, membersCount: 0 });
    await expect(page.locator("#organizationNotice")).toContainText("真实成员");
    await expect(page.locator("#organizationMembers")).toContainText("该机构暂无其他成员记录");
    await expect(page.locator("body")).not.toContainText("尚未加入机构");

    await page.unroute(/\/api\/org\/members(?:\?.*)?$/);
    await page.route(/\/api\/org\/members(?:\?.*)?$/, (route) => route.fulfill({ status: 500, json: { members: [] } }));
    await waitForOrganizationLoad(page, () => page.reload(), { meStatus: 200, membersStatus: 500, membersCount: 0 });
    await expect(page.locator("#organizationNotice")).toContainText("成员信息暂时无法读取");
    await expect(page.locator("#organizationMembers")).toContainText("成员信息暂时无法读取");
    await expect(page.locator("body")).not.toContainText("尚未加入机构");
    expect(consoleMessages).toContainEqual(expect.stringContaining("[org-members] member request failed"));

    await page.unroute(/\/api\/org\/me(?:\?.*)?$/);
    await page.unroute(/\/api\/org\/members(?:\?.*)?$/);
    await page.route(/\/api\/org\/me(?:\?.*)?$/, (route) => route.fulfill({ json: { organization: null, role: null, seats: null, plan: null } }));
    await page.route(/\/api\/org\/members(?:\?.*)?$/, (route) => route.fulfill({ json: { members: [] } }));
    await waitForOrganizationLoad(page, () => page.reload(), { meStatus: 200, membersStatus: 200, membersCount: 0 });
    await expect(page.locator("#organizationNotice")).toContainText("尚未加入机构");
    await expect(page.locator("#organizationMembers")).toContainText("尚未加入机构");

    await page.unroute(/\/api\/org\/me(?:\?.*)?$/);
    await page.unroute(/\/api\/org\/members(?:\?.*)?$/);
    await page.route(/\/api\/org\/me(?:\?.*)?$/, (route) => route.fulfill({ status: 503, json: { error: { code: "org_unavailable", message: "机构信息暂时无法读取。" } } }));
    await page.route(/\/api\/org\/members(?:\?.*)?$/, (route) => route.fulfill({ status: 503, json: { error: { code: "org_unavailable", message: "机构成员暂时无法读取。" } } }));
    await waitForOrganizationLoad(page, () => page.reload(), { meStatus: 503, waitForMembers: false });
    await expect(page.locator("#organizationNotice")).toContainText("暂时无法读取");
    await expect(page.locator("#organizationMembers")).toContainText("暂时无法读取");

    await page.goto("/billing.html");
    await expect(page.locator("#billingCurrentPlan")).toHaveText("暂无真实数据");
    await expect(page.locator("#billingPrice")).toHaveText("");
    await expect(page.locator("#autoRenewButton")).toHaveText("打开账单门户");
    await expect(page.locator("#autoRenewButton")).toBeDisabled();
    await expect(page.locator("#billingNotice")).toContainText("尚未接通");

  const billingSubscription = { plan: "B Data Pro", status: "active", current_period_end: "2026-10-01", cancel_at_period_end: false };
  await page.route("**/api/billing/prices", (route) => route.fulfill({ json: [{ product_code: "B_DATA_PRO", currency: "JPY", amount_minor: 399900, mode: "subscription" }] }));
  await page.route("**/api/me", (route) => route.fulfill({ json: { membership_tier: "B Data Pro" } }));
  await page.route("**/api/billing/subscription", (route) => route.fulfill({ json: billingSubscription }));
  await page.reload();
  await expect(page.locator("#billingCurrentPlan")).toHaveText("B Data Pro");
  await expect(page.locator("#billingPrice")).toContainText("正常");
  await expect(page.locator("#billingPlans .business-card")).toHaveCount(1);
  await expect(page.locator("#autoRenewButton")).toBeEnabled();
  await expect(page.locator("#billingNotice")).toContainText("真实账单价格");

  await page.route("**/api/usage/summary", (route) => route.fulfill({
    json: {
      available: true,
      period: { start: "2026-09-01", end: "2026-09-30" },
      entitlements: {
        queries: { used: 2, limit: 10 },
        reports: { used: 1, limit: null },
        exports_rows: { used: 2, limit: 10 },
      },
    },
  }));
  await page.goto("/usage.html");
  await expect(page.locator("#usageCards .business-card")).toHaveCount(3);
  await expect(page.locator("#usageCards")).toContainText("数据查询");
  await expect(page.locator("#usageCards")).toContainText("2 / 10");
  await expect(page.locator("#usageCards")).toContainText("未配置上限");
  await expect(page.locator("#usagePeriod")).toContainText("2026-09-01");
  await expect(page.locator("#usageNotice")).toContainText("已读取当前用户真实用量");
    await expect(page.locator("#usageList")).toContainText("汇总");

  await page.unroute("**/api/usage/summary");
  await page.route("**/api/usage/summary", (route) => route.fulfill({ status: 500, json: {} }));
  await page.reload();
    await expect(page.locator("#usageNotice")).toContainText("没有用量读取端点");
  } catch (error) {
    console.log("[org-members diagnostic] failure");
    console.log(`[org-members diagnostic] requests\n${requests.join("\n") || "(none)"}`);
    console.log(`[org-members diagnostic] console\n${consoleMessages.join("\n") || "(none)"}`);
    console.log(`[org-members diagnostic] pageerrors\n${pageErrors.join("\n") || "(none)"}`);
    console.log(`[org-members diagnostic] organizationNotice\n${await page.locator("#organizationNotice").innerText().catch(() => "(unavailable)")}`);
    console.log(`[org-members diagnostic] organizationMembers\n${await page.locator("#organizationMembers").innerText().catch(() => "(unavailable)")}`);
    throw error;
  }
});

test("订阅和服务任务页连接真实接口，导出页连接真实接口", async ({ page }) => {
  await seedBusinessReleaseScope(page);
  let subscription = null;
  await page.route("**/api/billing/subscription", (route) => route.fulfill({ json: subscription }));
  await page.goto("/subscriptions.html");
  await expect(page.locator("#subscriptionList")).toContainText("未订阅");
  await expect(page.locator("#subscriptionNotice")).toContainText("没有可读取的订阅记录");

  subscription = { plan: "B Free", status: "active", current_period_end: "2026-10-01", cancel_at_period_end: true };
  await page.reload();
  await expect(page.locator("#subscriptionList .business-list-row")).toHaveCount(1);
  await expect(page.locator("#subscriptionList")).toContainText("B Free");
  await expect(page.locator("#subscriptionList")).toContainText("周期末取消");
  await expect(page.locator("#subscriptionNotice")).toContainText("真实订阅");

  let exportCreated = false;
  await page.route("**/api/usage/summary", (route) => route.fulfill({ json: { available: true, entitlements: { exports_rows: { used: 2, limit: 10 } } } }));
  await page.route("**/api/exports", (route) => {
    if (route.request().method() === "POST") {
      exportCreated = true;
      return route.fulfill({ json: { id: "export-1", status: "completed", row_count: 2, created_at: "2026-09-12T00:00:00Z", download_url: "/api/exports/export-1", reused: false } });
    }
    return route.fulfill({ json: { exports: exportCreated ? [{ id: "export-1", status: "completed", row_count: 2, created_at: "2026-09-12T00:00:00Z" }] : [] } });
  });
  await page.goto("/exports.html");
  await page.locator("#exportForm button[type='submit']").click();
  await expect(page.locator("#exportList [data-export-row]")).toHaveCount(1);
  await expect(page.locator("#exportNotice")).toContainText("创建");

  let taskApplicationStatus = null;
  await page.route("**/api/org/service-tasks", (route) => route.fulfill({ json: { items: [{ id: "task-1", purpose: "现场看房协助", region_pref: "大阪", asset_type: "apartment", compensation: "paid", public_description: "需要机构协助现场看房并提供客观记录。", status: "open", application_status: taskApplicationStatus }] } }));
  await page.route("**/api/org/service-tasks/task-1/apply", (route) => { taskApplicationStatus = "pending"; return route.fulfill({ json: { task_id: "task-1", status: "pending", idempotent: false } }); });
  await page.route("**/api/org/service-tasks/task-1/withdraw", (route) => { taskApplicationStatus = "withdrawn"; return route.fulfill({ json: { task_id: "task-1", status: "withdrawn", idempotent: false } }); });
  await page.goto("/service-tasks.html");
  await page.locator("#taskFilter").selectOption("open");
  await expect(page.locator("#taskList [data-task-row]")).toHaveCount(1);
  await page.locator("[data-task-action='apply']").click();
  await expect(page.locator("#taskNotice")).toContainText("申请");
  await page.locator("[data-task-action='withdraw']").click();
  await expect(page.locator("#taskNotice")).toContainText("撤回");
});

test("导出提交期间禁用主按钮并提示沿用的导出", async ({ page }) => {
  await seedBusinessReleaseScope(page);
  let releasePost;
  const postBlocked = new Promise((resolve) => { releasePost = resolve; });
  await page.route("**/api/org/me", (route) => route.fulfill({ json: { organization: null, role: null, seats: null, plan: null } }));
  await page.route("**/api/usage/summary", (route) => route.fulfill({ json: { available: true, entitlements: { exports_rows: { used: 0, limit: 10 } } } }));
  await page.route("**/api/exports", async (route) => {
    if (route.request().method() === "POST") {
      await postBlocked;
      return route.fulfill({ json: { id: "export-1", status: "completed", row_count: 1, created_at: "2026-09-16T00:00:00Z", reused: true } });
    }
    return route.fulfill({ json: { exports: [] } });
  });
  await page.goto("/exports.html");
  const button = page.locator("#exportForm button[type='submit']");
  await button.click();
  await expect(button).toBeDisabled();
  await expect(button).toHaveText("正在提交……");
  releasePost();
  await expect(button).toBeEnabled();
  await expect(page.locator("#exportNotice")).toContainText("沿用刚刚生成的导出");
});

test("补齐的 B 端页面支持英文和日文切换", async ({ page }) => {
  await page.goto("/billing.html");

  await page.locator("[data-locale-switcher]").selectOption("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("h1")).toHaveText("Plans & billing");
  await expect(page.locator('[data-i18n="business.currency"]')).toHaveText("Display currency");

  await page.locator("[data-locale-switcher]").selectOption("ja");
  await expect(page.locator("html")).toHaveAttribute("lang", "ja");
  await expect(page.locator("h1")).toHaveText("プランと請求");
  await expect(page.locator('[data-i18n="business.currency"]')).toHaveText("表示通貨");
});

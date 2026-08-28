const { test, expect } = require("@playwright/test");

const demoSession = { username: "Demo User", email: "demo@example.com", provider: "local" };

async function seedSession(page, locale = "zh-CN") {
  await page.addInitScript(({ session, locale: initialLocale }) => {
    localStorage.setItem("zou_house_session", JSON.stringify(session));
    localStorage.setItem("zou_ui_locale", initialLocale);
  }, { session: demoSession, locale });
}

test("B 端主页保持精简并展示无图片的日元最近更新", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/index.html");
  await expect(page.locator("body.auth-ready")).toBeVisible();

  await expect(page.locator("#queryPanel")).toHaveCount(0);
  await expect(page.locator(".business-overview")).toHaveCount(0);
  await expect(page.locator(".service-task-panel")).toHaveCount(0);
  await expect(page.locator(".business-latest-panel .latest-card")).toHaveCount(5);
  await expect(page.locator(".business-latest-panel .latest-card img")).toHaveCount(0);
  await expect(page.locator(".business-latest-panel .latest-currency")).toHaveText(["¥", "¥", "¥", "¥", "¥"]);
  await expect(page.getByRole("link", { name: "数据查询" }).first()).toHaveAttribute("href", "data-query.html");

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
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
    await expect(page.locator(".business-demo-label, .business-fixture-note").first()).toContainText("synthetic_fixture");
    await expect(page.locator("[data-locale-switcher]")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);

    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.setViewportSize({ width: 1440, height: 900 });
  }

  expect(browserErrors).toEqual([]);
});

test("机构、账单和用量页提供本地演示操作", async ({ page }) => {
  await page.goto("/organization.html");
  await page.locator("#inviteMemberButton").click();
  await expect(page.locator("#organizationNotice")).toContainText("邀请流程演示");
  await page.locator("[data-member-action='view']").first().click();
  await expect(page.locator("#organizationNotice")).toContainText("成员详情");

  await page.goto("/billing.html");
  await page.locator("#billingCurrency").selectOption("JPY");
  await expect(page.locator("#billingPrice")).toContainText("3,999");
  await page.locator("#autoRenewButton").click();
  await expect(page.locator("#autoRenewButton")).toContainText("开启");
  await expect(page.locator("#billingNotice")).toContainText("演示");

  await page.goto("/usage.html");
  await page.locator("#usageFilter").selectOption("query");
  await expect(page.locator("#usageList [data-usage-kind='query']")).toHaveCount(2);
  await expect(page.locator("#usageNotice")).toContainText("查询");
});

test("订阅、导出和服务任务页提供本地演示操作", async ({ page }) => {
  await page.goto("/subscriptions.html");
  await page.locator("#subscriptionForm button[type='submit']").click();
  await expect(page.locator("#subscriptionList [data-subscription-row]")).toHaveCount(4);
  await expect(page.locator("#subscriptionNotice")).toContainText("添加");
  await page.locator("[data-subscription-action='toggle']").first().click();
  await expect(page.locator("#subscriptionNotice")).toContainText("本地");

  await page.goto("/exports.html");
  await page.locator("#exportForm button[type='submit']").click();
  await expect(page.locator("#exportList [data-export-row]")).toHaveCount(3);
  await expect(page.locator("#exportNotice")).toContainText("创建");

  await page.goto("/service-tasks.html");
  await page.locator("#taskFilter").selectOption("open");
  await expect(page.locator("#taskList [data-task-row]")).toHaveCount(1);
  await page.locator("[data-task-action='apply']").click();
  await expect(page.locator("#taskNotice")).toContainText("申请");
  await page.locator("[data-task-action='withdraw']").click();
  await expect(page.locator("#taskNotice")).toContainText("撤回");
});

test("补齐的 B 端页面支持英文和日文切换", async ({ page }) => {
  await page.goto("/billing.html");

  await page.locator("[data-locale-switcher]").selectOption("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("h1")).toHaveText("Plans & billing");
  await expect(page.locator("#autoRenewButton")).toContainText("auto-renew");

  await page.locator("[data-locale-switcher]").selectOption("ja");
  await expect(page.locator("html")).toHaveAttribute("lang", "ja");
  await expect(page.locator("h1")).toHaveText("プランと請求");
  await expect(page.locator("#autoRenewButton")).toContainText("自動更新");
});

const { test, expect } = require("@playwright/test");

const demoSession = {
  username: "Demo User",
  email: "demo@example.com",
  provider: "demo",
  accessToken: "test-token",
};

async function seedSession(page, locale = "zh-CN") {
  await page.addInitScript(({ session, initialLocale }) => {
    localStorage.setItem("zou_house_session", JSON.stringify(session));
    localStorage.setItem("zou_ui_locale", initialLocale);
  }, { session: demoSession, initialLocale: locale });
}

function assertNoInternalStatuses(page) {
  return expect(page.locator("body")).not.toContainText(/matched_pending_consent|completion_pending|in_progress|closed_unconfirmed|match_expired/);
}

test("B 端任务池渲染真实状态并调用申请、撤回、授权和完成端点", async ({ page }) => {
  await seedSession(page);
  let applicationStatus = null;
  let taskStatus = "open";
  const requests = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({ method: request.method(), path: url.pathname });
    if (url.pathname === "/api/org/service-tasks" && request.method() === "GET") {
      return route.fulfill({ json: { items: [{ id: "task-1", purpose: "现场看房协助", region_pref: "大阪", asset_type: "apartment", compensation: "paid", public_description: "需要机构协助现场看房。", status: taskStatus, application_status: applicationStatus }] } });
    }
    if (url.pathname.endsWith("/apply")) {
      applicationStatus = "pending";
      return route.fulfill({ json: { task_id: "task-1", status: "pending" } });
    }
    if (url.pathname.endsWith("/withdraw")) {
      applicationStatus = "withdrawn";
      return route.fulfill({ json: { task_id: "task-1", status: "withdrawn" } });
    }
    if (url.pathname.endsWith("/consent")) {
      taskStatus = "in_progress";
      return route.fulfill({ json: { task_id: "task-1", status: taskStatus } });
    }
    if (url.pathname.endsWith("/complete")) {
      taskStatus = "completion_pending";
      return route.fulfill({ json: { task_id: "task-1", status: taskStatus } });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto("/service-tasks.html");
  await expect(page.locator("[data-task-row]")).toHaveCount(1);
  await expect(page.locator("[data-task-action='apply']")).toHaveText("申请承接");
  await page.locator("[data-task-action='apply']").click();
  await expect(page.locator("[data-task-action='withdraw']")).toHaveText("撤回");
  await page.locator("[data-task-action='withdraw']").click();

  taskStatus = "matched_pending_consent";
  applicationStatus = null;
  await page.reload();
  await expect(page.locator("[data-task-action='consent']")).toHaveText("授权联系方式");
  await page.locator("[data-task-action='consent']").click();

  await expect(page.locator("[data-task-action='complete']")).toHaveText("申请完成");
  await page.locator("[data-task-action='complete']").click();
  await expect(page.locator("[data-task-row]")).toContainText("待确认完成");
  await assertNoInternalStatuses(page);
  await expect(page.locator("body")).not.toContainText("synthetic_fixture");
  expect(requests).toEqual(expect.arrayContaining([
    { method: "POST", path: "/api/org/service-tasks/task-1/apply" },
    { method: "POST", path: "/api/org/service-tasks/task-1/withdraw" },
    { method: "POST", path: "/api/org/service-tasks/task-1/consent" },
    { method: "POST", path: "/api/org/service-tasks/task-1/complete" },
  ]));
});

test("B 端任务池显示空态、失败态和无权限态", async ({ page }) => {
  await seedSession(page);
  let response = { status: 200, body: { items: [] } };
  await page.route("**/api/org/service-tasks", (route) => route.fulfill({ status: response.status, json: response.body }));
  await page.goto("/service-tasks.html");
  await expect(page.locator("#taskList")).toContainText("暂无可见任务");
  response = { status: 403, body: { error: { message: "forbidden" } } };
  await page.reload();
  await expect(page.locator("#taskNotice")).toContainText("任务服务暂时不可用");
  await assertNoInternalStatuses(page);
});

test("C 端服务任务支持未登录、空态、失败态和授权/完成动作", async ({ page }) => {
  let mode = "logged-out";
  let taskStatus = "matched_pending_consent";
  let creatorConsentStatus = "pending";
  const requests = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/service/tasks")) return route.fulfill({ json: {} });
    requests.push({ method: request.method(), url: request.url() });
    if (mode === "empty") return route.fulfill({ json: { items: [] } });
    if (mode === "failed") return route.fulfill({ status: 500, json: { error: { message: "failed" } } });
    return route.fulfill({ json: { items: [{ id: "task-c-1", purpose: "专家分析", public_description: "请协助分析。", status: taskStatus, creator_consent_status: creatorConsentStatus }] } });
  });

  await page.goto("/mypage.html");
  await expect(page.locator("#creatorServiceTaskList")).toContainText("登录后查看你创建的服务任务");

  await seedSession(page);
  mode = "empty";
  await page.reload();
  await expect(page.locator("#creatorServiceTaskList")).toContainText("暂无由你创建的服务任务");
  mode = "failed";
  await page.reload();
  await expect(page.locator("#creatorServiceTaskList")).toContainText("服务任务暂时无法加载");

  mode = "data";
  await page.reload();
  await expect(page.locator("[data-consent-task='task-c-1']")).toHaveText("授权联系方式");
  await page.locator("[data-consent-task='task-c-1']").click();
  creatorConsentStatus = "granted";
  await page.reload();
  await expect(page.locator("#creatorServiceTaskList")).toContainText("我方已授权，等待对方授权");

  taskStatus = "completion_pending";
  await page.reload();
  await expect(page.locator("[data-confirm-task='task-c-1']")).toHaveText("确认完成");
  await page.locator("[data-confirm-task='task-c-1']").click();
  await assertNoInternalStatuses(page);
  expect(requests).toEqual(expect.arrayContaining([
    { method: "POST", url: expect.stringContaining("/api/service/tasks/task-c-1/consent") },
    { method: "POST", url: expect.stringContaining("/api/service/tasks/task-c-1/confirm-completion") },
  ]));
});

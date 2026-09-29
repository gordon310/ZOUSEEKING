const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_API_BASE_URL = "http://127.0.0.1:8787";
    window.localStorage.setItem("sb-zou-house-auth-token", JSON.stringify({
      access_token: "projects-access-token",
      refresh_token: "projects-refresh-token",
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: "projects-user", email: "projects@example.com", user_metadata: { username: "项目用户" } },
    }));
  });
  await page.route("**/api/my/queries", async (route) => {
    expect(route.request().headers().authorization).toBe("Bearer projects-access-token");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          query_key: "大阪府::大阪市::北区::塔楼::2026::9",
          prefecture: "大阪府",
          city: "大阪市",
          ward: "北区",
          asset_type: "塔楼",
          year: 2026,
          month: 9,
          status: "pending",
          created_at: "2026-09-29T08:30:00Z",
          generation_jobs: [{ status: "running", progress: 42, current_step: "正在计算分析指标" }],
        },
      ]),
    });
  });
});

test("projects page renders authenticated query records instead of demo cards", async ({ page }) => {
  await page.goto("/projects.html");

  await expect(page.locator("#projectList")).toContainText("大阪府大阪市北区・塔楼");
  await expect(page.locator("#projectList")).toContainText("生成中");
  await expect(page.locator("#projectList")).not.toContainText("演示项目");
  await expect(page.locator("#projectsAuthState")).toBeHidden();
});

test("anonymous project list shows the registration gate", async ({ page }) => {
  await page.addInitScript(() => localStorage.clear());
  await page.goto("/projects.html");

  await expect(page.locator("#projectsAuthState")).toBeVisible();
  await expect(page.locator(".project-list-shell")).toBeHidden();
  await expect(page.locator("#projectsAuthState a")).toHaveAttribute("href", /profile\.html\?role=consumer&return_to=projects\.html/);
});

test("review project list keeps its data when status filter changes", async ({ page }) => {
  await page.goto("/projects.html?demo=1");

  await page.locator("#statusFilter").selectOption("running");
  await expect(page.locator("#projectList")).toContainText("大阪市中央区・公寓演示项目");
  await expect(page.locator("#projectList")).not.toContainText("大阪市北区・塔楼演示项目");
});

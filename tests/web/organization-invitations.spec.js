const { test, expect } = require("@playwright/test");

async function mockOrganization(page, role = "owner") {
  await page.addInitScript(() => { window.ZOUSEEKING_API_BASE_URL = "http://api.test"; window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true }; });
  await page.route("**/api/org/me", (route) => route.fulfill({ json: { organization: { name: "测试机构" }, role, seats: { used: 1, limit: 5 }, plan: { name: "B Free" } } }));
  await page.route("**/api/org/members", (route) => route.fulfill({ json: { members: [{ display_name: "o***@local.test", role: "owner", status: "active", joined_at: "2026-09-16" }] } }));
  await page.route("**/api/org/invitations", (route) => route.fulfill({ json: { invitations: [] } }));
}

test("owner sees invite action", async ({ page }) => {
  await mockOrganization(page, "owner");
  await page.goto("/organization.html");
  await expect(page.getByRole("button", { name: "邀请成员" })).toBeVisible();
});

test("member has no invite action", async ({ page }) => {
  await mockOrganization(page, "member");
  await page.goto("/organization.html");
  await expect(page.getByRole("button", { name: "邀请成员" })).toBeHidden();
});

test("owner sees one-time link and copy control after creation", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await mockOrganization(page, "owner");
  await page.route("**/api/org/invitations", async (route) => {
    if (route.request().method() === "POST") return route.fulfill({ json: { invite_token: "one-time-token", expires_at: "2026-09-23T00:00:00Z" } });
    return route.fulfill({ json: { invitations: [] } });
  });
  await page.goto("/organization.html");
  await page.getByLabel("受邀邮箱").fill("new@example.com");
  await page.getByRole("button", { name: "生成一次性链接" }).click();
  await expect(page.getByText("链接仅显示一次")).toBeVisible();
  await expect(page.getByRole("button", { name: "复制邀请链接" })).toBeVisible();
  await page.getByRole("button", { name: "复制邀请链接" }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain("invite.html?token=one-time-token");
});

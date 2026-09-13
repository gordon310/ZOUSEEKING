const { test, expect } = require("@playwright/test");

// Config.js now ships a default staging Supabase endpoint, so the "not
// configured" branch is not reachable via window overrides (|| keeps non-empty
// values). These tests simulate an unreachable auth service instead: the core
// guarantee under test is that NO local password credentials are ever created
// or consumed, and no session is stored on failure.
const UNREACHABLE_SUPABASE = `
  window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
  window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
`;

async function blockSupabase(page) {
  await page.route("https://supabase.test/**", (route) => route.abort());
}

test("注册在认证服务不可达时不创建本地密码凭据", async ({ page }) => {
  await page.addInitScript(UNREACHABLE_SUPABASE);
  await blockSupabase(page);
  await page.goto("/data-query.html");
  await page.getByRole("button", { name: "注册" }).click();
  await page.locator("#registerConsent").check();
  await page.getByLabel("用户名").fill("local-only-user");
  await page.locator("#registerEmail").fill("local-only@example.com");
  await page.locator("#registerPassword").fill("Correct Horse Battery Staple");
  await page.getByRole("button", { name: "注册并登录" }).click();

  await expect(page.locator("#formMessage")).toContainText("注册未完成");
  await expect(page).toHaveURL(/data-query\.html/);
  expect(await page.evaluate(() => localStorage.getItem("zou_house_users"))).toBeNull();
  expect(await page.evaluate(() => localStorage.getItem("zou_house_session"))).toBeNull();
});

test("登录在认证服务不可达时不消费本地密码凭据", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
    localStorage.setItem(
      "zou_house_users",
      JSON.stringify([
        {
          username: "legacy-user",
          email: "legacy@example.com",
          passwordHash: "af139fa284364215adfa49c889ab7feddc5e5d1c52512ffb2cfc9baeb67f220e",
        },
      ]),
    );
  });
  await blockSupabase(page);
  await page.goto("/data-query.html");
  await page.locator("#loginUsername").fill("legacy@example.com");
  await page.locator("#loginPassword").fill("Correct Horse Battery Staple");
  await page.getByRole("button", { name: "登录查询" }).click();

  await expect(page.locator("#formMessage")).toContainText("邮箱或密码不正确，或账户暂不可用");
  expect(await page.evaluate(() => localStorage.getItem("zou_house_session"))).toBeNull();
});

test("认证会话变更事件会立即刷新首页登录状态，登出后立即清空", async ({ page }) => {
  await page.route("**/auth/v1/**", (route) => route.abort());
  await page.goto("/index.html");
  await expect(page.locator("body.auth-ready")).toBeVisible();

  await page.evaluate(() => {
    window.ZouAuthSession.write({
      provider: "supabase",
      username: "Gordon",
      email: "gordon@example.com",
      userId: "user-1",
      accessToken: "fresh-token",
      refreshToken: "refresh-token",
      expiresAt: Math.floor(Date.now() / 1000) + 3600,
    });
  });
  await expect(page.locator("#accountTitle")).toHaveText("你好，Gordon");
  await expect(page.locator("#logoutButton")).toBeVisible();
  await expect(page.locator("#accountCopy")).toContainText("gordon@example.com");

  await page.evaluate(() => window.ZouAuthSession.write(null));
  await expect(page.locator("#accountTitle")).toHaveText("登录后可以查询");
  await expect(page.locator("#logoutButton")).toBeHidden();
});

test("真实形状的 Supabase 登录响应会持久化会话并进入已登录状态", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
    window.ZOUSEEKING_API_BASE_URL = "https://api.test";
  });
  await page.route("https://supabase.test/auth/v1/token?grant_type=password", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "eyJhbGciOiJFUzI1NiIs.test-access",
        refresh_token: "test-refresh-token",
        expires_in: 3600,
        token_type: "bearer",
        user: { id: "12894fa8-test", email: "member@example.com", user_metadata: { username: "member" } },
      }),
    });
  });
  await page.route("https://supabase.test/rest/v1/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("https://api.test/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.goto("/index.html");
  await page.locator("#loginUsername").fill("member@example.com");
  await page.locator("#loginPassword").fill("correct password");
  await page.getByRole("button", { name: "登录查询" }).click();

  await expect(page.locator("#formMessage")).toHaveText("登录成功，可以搜了。");
  await expect(page.locator("#accountTitle")).toHaveText("你好，member");
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("sb-supabase-auth-token")));
  expect(stored.access_token).toBeTruthy();
  expect(stored.expires_at).toBeGreaterThan(Math.floor(Date.now() / 1000) + 60);
  expect(await page.evaluate(() => window.ZouAuthSession.isLoggedIn())).toBe(true);
  expect(await page.locator("#formMessage").textContent()).not.toContain("邮箱或密码不正确");
});

test("只有密码登录 400 才显示凭证错误，服务错误显示其它文案", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
  });
  await page.route("https://supabase.test/auth/v1/token?grant_type=password", async (route) => {
    await route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "invalid_grant" }) });
  });
  await page.goto("/index.html");
  await page.locator("#loginUsername").fill("member@example.com");
  await page.locator("#loginPassword").fill("wrong password");
  await page.getByRole("button", { name: "登录查询" }).click();
  await expect(page.locator("#formMessage")).toHaveText("邮箱或密码不正确，或账户暂不可用。");

  await page.unroute("https://supabase.test/auth/v1/token?grant_type=password");
  await page.route("https://supabase.test/auth/v1/token?grant_type=password", async (route) => {
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "server_error" }) });
  });
  await page.locator("#loginUsername").fill("member@example.com");
  await page.locator("#loginPassword").fill("temporary failure");
  await page.getByRole("button", { name: "登录查询" }).click();
  await expect(page.locator("#formMessage")).toHaveText("登录服务暂时不可用，请稍后重试。");
  await expect(page.locator("#formMessage")).not.toContainText("邮箱或密码不正确");
});

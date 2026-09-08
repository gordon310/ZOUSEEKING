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

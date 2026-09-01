const { test, expect } = require("@playwright/test");

test("未配置 Supabase 时注册不会创建本地密码凭据", async ({ page }) => {
  await page.goto("/data-query.html");
  await page.getByRole("button", { name: "注册" }).click();
  await page.locator("#registerConsent").check();
  await page.getByLabel("用户名").fill("local-only-user");
  await page.locator("#registerEmail").fill("local-only@example.com");
  await page.locator("#registerPassword").fill("Correct Horse Battery Staple");
  await page.getByRole("button", { name: "注册并登录" }).click();

  await expect(page.locator("#formMessage")).toContainText("账户服务还未配置");
  await expect(page).toHaveURL(/data-query\.html/);
  expect(await page.evaluate(() => localStorage.getItem("zou_house_users"))).toBeNull();
  expect(await page.evaluate(() => localStorage.getItem("zou_house_session"))).toBeNull();
});

test("未配置 Supabase 时登录不会消费本地密码凭据", async ({ page }) => {
  await page.addInitScript(() => {
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
  await page.goto("/data-query.html");
  await page.locator("#loginUsername").fill("legacy@example.com");
  await page.locator("#loginPassword").fill("Correct Horse Battery Staple");
  await page.getByRole("button", { name: "登录查询" }).click();

  await expect(page.locator("#formMessage")).toContainText("账户服务还未配置");
  expect(await page.evaluate(() => localStorage.getItem("zou_house_session"))).toBeNull();
});

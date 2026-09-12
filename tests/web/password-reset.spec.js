const { test, expect } = require("@playwright/test");

const UNREACHABLE_SUPABASE = () => {
  window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
  window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
};

test("all five account pages turn forgot password into an inline form", async ({ page }) => {
  for (const path of ["index.html", "mypage.html", "profile.html", "analysis.html", "data-query.html"]) {
    await page.goto(`/${path}`);
    await page.locator("#forgotPasswordLink").click();
    await expect(page.locator("#forgotPasswordForm")).toBeVisible();
    await expect(page.locator("#loginForm")).toBeHidden();
  }
});

test("reset request uses current-origin destination and one neutral success copy", async ({ page }) => {
  await page.addInitScript(UNREACHABLE_SUPABASE);
  let requestedRedirect = "";
  await page.route("https://supabase.test/auth/v1/recover**", async (route) => {
    requestedRedirect = new URL(route.request().url()).searchParams.get("redirect_to");
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.goto("/data-query.html");
  await page.locator("#forgotPasswordLink").click();
  await page.locator("#forgotPasswordEmail").fill("unknown@example.com");
  const submit = page.locator("#forgotPasswordForm button[type=submit]");
  await submit.click();
  await expect(page.locator("#formMessage")).toContainText("如果该邮箱已注册");
  expect(requestedRedirect).toBe("http://127.0.0.1:8787/reset-password.html");
});

test("reset page only shows the form for a valid recovery session", async ({ page }) => {
  await page.addInitScript(UNREACHABLE_SUPABASE);
  await page.route("https://supabase.test/auth/v1/user", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { id: "user-1" } }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.goto("/reset-password.html");
  await expect(page.locator("#resetPasswordForm")).toBeHidden();
  await expect(page.locator("#resetInvalidState")).toBeVisible();

  await page.goto("/reset-password.html#access_token=recovery-token&type=recovery&refresh_token=refresh-token");
  await expect(page.locator("#resetPasswordForm")).toBeVisible();
  await page.locator("#resetNewPassword").fill("valid password 123");
  await page.locator("#resetConfirmPassword").fill("different password");
  await page.getByRole("button", { name: "更新密码" }).click();
  await expect(page.locator("#resetStatus")).toContainText("两次输入的密码不一致");
});

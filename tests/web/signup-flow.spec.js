const { test, expect } = require("@playwright/test");

const SUPABASE_URL = "https://supabase.test";

async function openRegistration(page) {
  await page.addInitScript(() => {
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
  });
  await page.goto("/index.html");
  await page.getByRole("button", { name: "切换到注册" }).click();
  await page.locator("#registerConsent").check();
  await page.getByLabel("用户名").fill("signup-user");
  await page.locator("#registerEmail").fill("signup@example.com");
  await page.locator("#registerPassword").fill("sixsix");
}

test("注册响应没有会话时显示待确认状态和重发入口", async ({ page }) => {
  await openRegistration(page);
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/signup/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "new-user-id", email: "signup@example.com", user: { identities: [{}] } }),
    });
  });
  await page.getByRole("button", { name: "注册并登录" }).click();

  await expect(page.locator("#emailVerificationPanel")).toBeVisible();
  await expect(page.locator("#emailVerificationMessage")).toContainText("确认邮件已发送到 signup@example.com");
  await expect(page.locator("#emailVerificationMessage")).toContainText("邮件里的链接");
  await expect(page.getByRole("button", { name: "重新发送确认邮件" })).toBeVisible();
  await expect(page.locator("#accountTitle")).not.toContainText("你好");
});

test("已注册邮箱的空身份响应切到登录并提供找回密码入口", async ({ page }) => {
  await openRegistration(page);
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/signup/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "existing-user-id", email: "signup@example.com", identities: [] }),
    });
  });
  await page.getByRole("button", { name: "注册并登录" }).click();

  await expect(page.locator("#formMessage")).toHaveText("该邮箱已注册，请直接登录。");
  await expect(page.locator("#showLogin")).toBeVisible();
  await expect(page.locator("#loginForm")).toBeVisible();
  await expect(page.locator("#forgotPasswordLink")).toBeVisible();
  await page.locator("#forgotPasswordLink").click();
  await expect(page.locator("#forgotPasswordForm")).toBeVisible();
  await expect(page.locator("#emailVerificationPanel")).toBeHidden();
  await expect(page.locator("body")).not.toContainText("确认邮件已发送");
  await expect(page.locator("body")).not.toContainText("identities");
  await expect(page.getByRole("button", { name: /重新发送确认邮件/ })).toHaveCount(0);
});

test("注册命中邮件频率限制时显示专属提示而不宣称已发送", async ({ page }) => {
  await openRegistration(page);
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/signup/, async (route) => {
    await route.fulfill({
      status: 429,
      contentType: "application/json",
      body: JSON.stringify({ code: 429, error_code: "over_email_send_rate_limit", msg: "rate limited" }),
    });
  });
  await page.getByRole("button", { name: "注册并登录" }).click();

  await expect(page.locator("#formMessage")).toHaveText("邮件发送过于频繁，请稍后再试。");
  await expect(page.locator("body")).not.toContainText("已发送");
  await expect(page.locator("body")).not.toContainText("over_email_send_rate_limit");
  await expect(page.getByRole("button", { name: /重新发送确认邮件/ })).toHaveCount(0);
});

test("登录返回邮箱未验证时显示专属文案和重发入口", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
  });
  await page.goto("/index.html");
  await page.locator("#loginUsername").fill("unverified@example.com");
  await page.locator("#loginPassword").fill("sixsix");
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/token/, async (route) => {
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({ error_code: "email_not_confirmed", msg: "Email not confirmed" }),
    });
  });
  await page.getByRole("button", { name: "登录查询" }).click();

  await expect(page.locator("#emailVerificationPanel")).toBeVisible();
  await expect(page.locator("#formMessage")).toContainText("邮箱尚未验证");
  await expect(page.locator("#formMessage")).not.toContainText("邮箱或密码不正确");
  await expect(page.getByRole("button", { name: "重新发送确认邮件" })).toBeVisible();
});

test("重新发送确认邮件使用 signup 语义且 60 秒内节流", async ({ page }) => {
  await openRegistration(page);
  let resendCount = 0;
  let resendBody;
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/signup/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "new-user-id", email: "signup@example.com", user: { identities: [{}] } }),
    });
  });
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/resend/, async (route) => {
    resendCount += 1;
    resendBody = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.getByRole("button", { name: "注册并登录" }).click();
  const resend = page.getByRole("button", { name: "重新发送确认邮件" });
  await resend.click();
  await expect(page.locator("#formMessage")).toContainText("确认邮件已重新发送");
  await resend.click();
  await expect(page.locator("#formMessage")).toContainText("请等待");
  expect(resendCount).toBe(1);
  expect(resendBody).toEqual({ type: "signup", email: "signup@example.com" });
});

test("注册返回会话时进入已登录状态并清理注册地址", async ({ page }) => {
  await page.addInitScript(() => {
    window.__signupResponse = {
      access_token: "signup-access-token",
      refresh_token: "signup-refresh-token",
      expires_in: 3600,
      user: { id: "signup-user-id", email: "signup@example.com", user_metadata: { username: "signup-user" } },
    };
  });
  await openRegistration(page);
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/signup/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "signup-access-token",
        refresh_token: "signup-refresh-token",
        expires_in: 3600,
        user: { id: "signup-user-id", email: "signup@example.com", user_metadata: { username: "signup-user" } },
      }),
    });
  });
  await page.route(`${SUPABASE_URL}/rest/v1/**`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.getByRole("button", { name: "注册并登录" }).click();

  await expect(page.locator("#accountTitle")).toHaveText("你好，signup-user");
  await expect(page.locator("#formMessage")).toContainText("注册成功，已登录");
  expect(new URL(page.url()).hash).toBe("");
});

test("注册失败时显示失败反馈并保持未登录", async ({ page }) => {
  await openRegistration(page);
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/signup/, async (route) => {
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "server_error" }) });
  });
  await page.getByRole("button", { name: "注册并登录" }).click();

  await expect(page.locator("#formMessage")).toHaveText("注册未完成，请稍后重试。");
  await expect(page.locator("#accountTitle")).not.toContainText("你好");
});

test("邮箱已注册时显示对应原因并保持未登录", async ({ page }) => {
  await openRegistration(page);
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/signup/, async (route) => {
    await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ error: "user_already_exists" }) });
  });
  await page.getByRole("button", { name: "注册并登录" }).click();

  await expect(page.locator("#formMessage")).toHaveText("该邮箱已注册，请直接登录。");
  await expect(page.locator("#accountTitle")).not.toContainText("你好");
});

test("注册页窄视口没有横向溢出且 tab 按钮完整可见", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/index.html");
  await page.getByRole("button", { name: "切换到注册" }).click();

  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  for (const id of ["showLogin", "showRegister"]) {
    const box = await page.locator(`#${id}`).boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);
  }
});

test("注册页不展示内部版本号或 UTC 实现说明", async ({ page }) => {
  await page.goto("/index.html");
  await page.getByRole("button", { name: "切换到注册" }).click();
  const text = await page.locator("#accountPanel").innerText();
  expect(text).not.toContain("privacy-2026-08");
  expect(text).not.toContain("UTC");
});

test("注册、修改密码和找回密码表单都常驻显示六到一百二十八位规则", async ({ page }) => {
  for (const path of ["index.html", "data-query.html", "mypage.html", "analysis.html", "profile.html"]) {
    await page.goto(`/${path}`);
    await page.getByRole("button", { name: /注册|切换到注册/ }).click();
    await expect(page.locator("#registerForm .password-rule")).toContainText("6–128");
  }
  await page.goto("/profile.html");
  await expect(page.locator("#passwordForm .password-rule")).toContainText("6–128");
  await page.goto("/reset-password.html");
  await expect(page.locator("#resetPasswordForm .password-rule")).toContainText("6–128");
});

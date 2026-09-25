const { test, expect } = require("@playwright/test");

const API_BASE_URL = "https://invite-api.test";

async function openRegistration(page, { email = "signup@example.com", inviteCode = "valid-invite" } = {}) {
  await page.addInitScript((apiBaseUrl) => {
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
    window.ZOUSEEKING_API_BASE_URL = apiBaseUrl;
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
  }, API_BASE_URL);
  await page.goto("/index.html");
  await page.getByRole("button", { name: "切换到注册" }).click();
  await page.locator("#registerConsent").check();
  await page.getByLabel("用户名").fill("signup-user");
  await page.locator("#registerEmail").fill(email);
  await page.locator("#registerPassword").fill("sixsix");
  if (inviteCode !== null) await page.locator("#registerInviteCode").fill(inviteCode);
}

async function submitRegistration(page) {
  await page.getByRole("button", { name: /注册账号|Create account/ }).click();
}

test("开放注册允许空邀请码，并发送完整注册请求", async ({ page }) => {
  let requestBody;
  await openRegistration(page, { inviteCode: null });
  await page.route("**/api/**", async (route) => {
    requestBody = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ user_id: "new-user-id", email: "signup@example.com" }) });
  });
  await expect(page.locator("#registerInviteCode")).not.toHaveAttribute("required", "");
  await submitRegistration(page);
  await expect(page.locator("#formMessage")).toHaveText("账户已创建;请完成邮箱确认后登录。");
  await expect(page.locator("#loginForm")).toBeVisible();
  expect(requestBody).toMatchObject({ email: "signup@example.com", password: "sixsix", username: "signup-user", invite_code: "", consent_version: "privacy-2026-08", terms_version: "terms-2026-08" });
});

test("带邀请码注册保留邀请码并发送完整注册请求", async ({ page }) => {
  let requestBody;
  await openRegistration(page, { inviteCode: "valid-invite" });
  await page.route("**/api/**", async (route) => {
    requestBody = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ user_id: "new-user-id", email: "signup@example.com" }) });
  });
  await submitRegistration(page);
  await expect(page.locator("#formMessage")).toHaveText("账户已创建;请完成邮箱确认后登录。");
  await expect(page.locator("#loginForm")).toBeVisible();
  expect(requestBody).toMatchObject({ email: "signup@example.com", password: "sixsix", username: "signup-user", invite_code: "valid-invite", consent_version: "privacy-2026-08", terms_version: "terms-2026-08" });
});

for (const [label, status, code, message] of [
  ["无效", 403, "invite_code_invalid", "邀请码无效、已停用或已过期。"],
  ["停用", 403, "invite_code_disabled", "邀请码已停用。"],
  ["过期", 403, "invite_code_expired", "邀请码已过期。"],
  ["耗尽", 409, "invite_code_exhausted", "邀请码已用尽。"],
]) {
test(`受邀注册将${label}邀请码错误显示为安全提示`, async ({ page }) => {
  await openRegistration(page);
  await page.route("**/api/**", (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ detail: { code } }) }));
  await submitRegistration(page);
  await expect(page.locator("#formMessage")).toHaveText(message);
  await expect(page.locator("#accountTitle")).not.toContainText("你好");
  await expect(page.locator("#formMessage")).not.toContainText(code);
});
}

test("同一单次邀请码并发提交时只有一次兑换成功", async ({ page, context }) => {
  const second = await context.newPage();
  let redemptions = 0;
  const requestBodies = [];
  await context.route("**/api/**", async (route) => {
    requestBodies.push(JSON.parse(route.request().postData() || "{}"));
    redemptions += 1;
    await route.fulfill(redemptions === 1
      ? { status: 201, contentType: "application/json", body: JSON.stringify({ user_id: "one", email: "signup@example.com" }) }
      : { status: 409, contentType: "application/json", body: JSON.stringify({ detail: { code: "invite_code_exhausted" } }) });
  });
  await Promise.all([openRegistration(page, { email: "first@example.com", inviteCode: "one-use-code" }), openRegistration(second, { email: "second@example.com", inviteCode: "one-use-code" })]);
  await Promise.all([submitRegistration(page), submitRegistration(second)]);
  await expect(page.locator("#formMessage")).toHaveText(/账户已创建;请完成邮箱确认后登录。|邀请码已用尽。/);
  await expect(second.locator("#formMessage")).toHaveText(/账户已创建;请完成邮箱确认后登录。|邀请码已用尽。/);
  expect(requestBodies).toHaveLength(2);
  expect(requestBodies.map((body) => body.invite_code)).toEqual(["one-use-code", "one-use-code"]);
  expect([await page.locator("#formMessage").textContent(), await second.locator("#formMessage").textContent()].sort()).toEqual(["账户已创建;请完成邮箱确认后登录。", "邀请码已用尽。"]);
  await second.close();
});

test("第六次受邀注册返回 429，并保留 Retry-After 合约", async ({ page }) => {
  let attempts = 0;
  let retryAfter;
  await page.route("**/api/**", async (route) => {
    attempts += 1;
    if (attempts <= 5) return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ user_id: `user-${attempts}`, email: `signup-${attempts}@example.com` }) });
    retryAfter = "3600";
    return route.fulfill({ status: 429, contentType: "application/json", headers: { "Retry-After": retryAfter }, body: JSON.stringify({ detail: { code: "rate_limited" } }) });
  });
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    await openRegistration(page, { email: `signup-${attempt}@example.com`, inviteCode: `rate-limit-${attempt}` });
    await submitRegistration(page);
    if (attempt <= 5) await expect(page.locator("#formMessage")).toHaveText("账户已创建;请完成邮箱确认后登录。");
  }
  expect(attempts).toBe(6);
  expect(retryAfter).toBe("3600");
  await expect(page.locator("#formMessage")).toHaveText("邮件发送过于频繁，请稍后再试。");
  await expect(page.locator("#formMessage")).not.toContainText("rate_limited");
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
  await page.route(/https:\/\/supabase\.test\/auth\/v1\/token/, (route) => route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error_code: "email_not_confirmed", msg: "Email not confirmed" }) }));
  await page.getByRole("button", { name: "登录查询" }).click();
  await expect(page.locator("#emailVerificationPanel")).toBeVisible();
  await expect(page.locator("#formMessage")).toContainText("邮箱尚未验证");
});

test("注册页窄视口没有横向溢出且邀请码输入完整可见", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/index.html");
  await page.getByRole("button", { name: "切换到注册" }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const box = await page.locator("#registerInviteCode").boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
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

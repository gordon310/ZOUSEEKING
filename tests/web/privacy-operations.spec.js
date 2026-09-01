const { test, expect } = require("@playwright/test");

const accountPages = ["index.html", "data-query.html", "analysis.html", "mypage.html", "profile.html"];

test("all account forms require versioned privacy and terms consent", async ({ page }) => {
  await page.route("**/content-library.json", async (route) => {
    await route.fulfill({ status: 404, contentType: "text/plain", body: "synthetic missing generated library" });
  });
  for (const route of accountPages) {
    await page.goto(`/${route}`);
    await page.getByRole("button", { name: "注册" }).click();
    await expect(page.locator("#registerConsent")).toBeVisible();
    await expect(page.locator("#registerForm")).toContainText("隐私政策");
    await expect(page.locator("#registerForm")).toContainText("服务条款");
    await expect(page.locator("#registerForm")).toContainText("privacy-2026-08");
    await expect(page.locator("#registerConsent")).toHaveAttribute("required", "");
  }
});

test("Supabase signup carries consent version and submission timestamp", async ({ page }) => {
  let signupBody;
  await page.addInitScript(() => {
    window.ZOUSEEKING_API_BASE_URL = "";
    window.ZOUSEEKING_SUPABASE_URL = "https://auth.example.invalid";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "publishable-test-key";
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
  });
  await page.route("https://auth.example.invalid/auth/v1/signup**", async (route) => {
    signupBody = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user: { id: "00000000-0000-0000-0000-000000000030", email: "member@example.invalid" } }),
    });
  });
  await page.goto("/index.html");
  await page.getByRole("button", { name: "注册" }).click();
  await page.locator("#registerUsername").fill("演示用户");
  await page.locator("#registerEmail").fill("member@example.invalid");
  await page.locator("#registerPassword").fill("not-a-real-password");
  await page.locator("#registerConsent").check();
  await page.locator("#registerForm button[type='submit']").click();

  await expect.poll(() => signupBody).toMatchObject({
    data: {
      username: "演示用户",
      consent_version: "privacy-2026-08",
      terms_version: "terms-2026-08",
      consent_source: "registration",
    },
  });
  expect(signupBody.data.consent_at).toMatch(/^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
});

test("profile deletion control is explicit and remains a no-op without API", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "zou_house_session",
      JSON.stringify({ username: "演示用户", email: "member@example.invalid", provider: "demo" }),
    );
  });
  await page.goto("/profile.html");
  await page.locator("#openDeleteAccountButton").click();
  await expect(page.locator("#deleteAccountDialog")).toBeVisible();
  await page.locator("#deleteAccountConfirm").check();
  await page.locator("#confirmDeleteAccountButton").click();
  await expect(page.locator("#formMessage")).toContainText("未删除任何内容");
});

test("forgot-password copy stays enumeration-safe", async ({ page }) => {
  await page.goto("/profile.html");
  await page.locator("#forgotPasswordLink").click();
  await expect(page.locator("#accountCopy")).toContainText("不会暴露账户是否存在");
});

test("password reset submits a uniform response without revealing account existence", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_SUPABASE_URL = "https://auth.example.invalid";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "publishable-test-key";
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
  });
  let resetBody;
  await page.route("https://auth.example.invalid/auth/v1/recover**", async (route) => {
    resetBody = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.goto("/profile.html");
  await page.locator("#forgotPasswordLink").click();
  await page.locator("#forgotPasswordEmail").fill("member@example.invalid");
  await page.locator("#forgotPasswordForm button[type='submit']").click();
  await expect(page.locator("#formMessage")).toContainText("如果这个邮箱已注册");
  await expect.poll(() => resetBody).toEqual({ email: "member@example.invalid" });
});

test("logout clears the local session when remote revocation fails", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_API_BASE_URL = "";
    window.ZOUSEEKING_SUPABASE_URL = "https://auth.example.invalid";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "publishable-test-key";
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
    localStorage.setItem(
      "zou_house_session",
      JSON.stringify({
        username: "演示用户",
        email: "member@example.invalid",
        userId: "00000000-0000-0000-0000-000000000030",
        accessToken: "synthetic-access-token",
        refreshToken: "synthetic-refresh-token",
        provider: "supabase",
      }),
    );
  });
  await page.route("https://auth.example.invalid/auth/v1/user", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000030", email: "member@example.invalid" }) });
  });
  await page.route("https://auth.example.invalid/rest/v1/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("https://auth.example.invalid/auth/v1/logout", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"synthetic unavailable"}' });
  });
  await page.goto("/profile.html");
  await expect(page.locator("body")).toHaveClass(/auth-ready/, { timeout: 10_000 });
  await expect(page.locator("#logoutButton")).toBeVisible();
  await page.locator("#logoutButton").click();
  await expect(page.locator("#logoutButton")).toBeHidden();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("zou_house_session"))).toBeNull();
});

test("privacy and account controls fit a 390px viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ["privacy.html", "terms.html", "support.html"]) {
    await page.goto(`/${route}`);
    await expect(page.locator("body")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  }
  await page.goto("/profile.html");
  await page.getByRole("button", { name: "注册" }).click();
  await expect(page.locator("#registerConsent")).toBeVisible();
});

test("login and signup errors stay enumeration-safe", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_SUPABASE_URL = "https://auth.example.invalid";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "publishable-test-key";
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
  });
  await page.route("https://auth.example.invalid/auth/v1/**", async (route) => {
    const body = route.request().url().includes("/signup")
      ? { msg: "User already registered", email: "member@example.invalid" }
      : { error_description: "Email not confirmed", email: "member@example.invalid" };
    await route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/profile.html");
  await page.locator("#loginUsername").fill("member@example.invalid");
  await page.locator("#loginPassword").fill("synthetic-password");
  await page.locator("#loginForm button[type='submit']").click();
  await expect(page.locator("#formMessage")).toContainText("邮箱或密码不正确，或账户暂不可用");
  await expect(page.locator("#formMessage")).not.toContainText("Email not confirmed");

  await page.locator("#showRegister").click();
  await page.locator("#registerUsername").fill("演示用户");
  await page.locator("#registerEmail").fill("member@example.invalid");
  await page.locator("#registerPassword").fill("synthetic-password");
  await page.locator("#registerConsent").check();
  await page.locator("#registerForm button[type='submit']").click();
  await expect(page.locator("#formMessage")).toContainText("注册未完成，请稍后再试");
  await expect(page.locator("#formMessage")).not.toContainText("User already registered");
});

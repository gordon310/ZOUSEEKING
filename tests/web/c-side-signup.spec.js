// C-side (consumer) registration on profile.html?role=consumer.
//
// Regression guard for a real production defect: app.js read
// $("#registerInviteCode").value unconditionally, but that element only
// exists on index.html. On profile.html?role=consumer - the page the C-side
// home page links to for sign-up - the read threw a TypeError before the
// field validation ran, so the button appeared to do nothing: no request,
// no message. This file deliberately drives profile.html (never index.html)
// and asserts the invite-code element is absent, so the scenario cannot be
// silently re-pointed at the page that happens to have the element.

const { test, expect } = require("@playwright/test");

const API_BASE_URL = "https://invite-api.test";

async function openConsumerRegistration(page) {
  await page.addInitScript((apiBaseUrl) => {
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
    window.ZOUSEEKING_API_BASE_URL = apiBaseUrl;
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
  }, API_BASE_URL);
  await page.goto("/profile.html?role=consumer");
  await page.locator("#showRegister").click();
  await expect(page.locator("#registerForm")).toBeVisible();
}

async function fillConsumerRegistration(page, { username = "c-side-user", email = "c-side@example.com", password = "sixsix" } = {}) {
  if (username !== null) await page.locator("#registerUsername").fill(username);
  if (email !== null) await page.locator("#registerEmail").fill(email);
  if (password !== null) await page.locator("#registerPassword").fill(password);
}

test("C 端注册页不存在邀请码字段（固化缺陷场景）", async ({ page }) => {
  await openConsumerRegistration(page);
  await expect(page.locator("#registerInviteCode")).toHaveCount(0);
  await expect(page.locator("#registerForm")).toBeVisible();
});

test("C 端注册：缺密码时给出内联提示，而不是静默无反应", async ({ page }) => {
  let apiCalled = false;
  await openConsumerRegistration(page);
  await page.route("**/api/**", async (route) => {
    apiCalled = true;
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ user_id: "u" }) });
  });
  await fillConsumerRegistration(page, { password: null });
  await page.locator("#registerConsent").check();
  await page.locator("#registerForm button[type='submit']").click();

  // The defect produced neither a request nor a message.
  await expect(page.locator("#formMessage")).not.toBeEmpty();
  expect(apiCalled).toBe(false);
});

test("C 端注册：缺用户名时给出内联提示", async ({ page }) => {
  await openConsumerRegistration(page);
  await fillConsumerRegistration(page, { username: "" });
  await page.locator("#registerConsent").check();
  await page.locator("#registerForm button[type='submit']").click();
  await expect(page.locator("#formMessage")).not.toBeEmpty();
});

test("C 端注册：未勾选同意时不发请求，表单保持可用", async ({ page }) => {
  let apiCalled = false;
  await openConsumerRegistration(page);
  await page.route("**/api/**", async (route) => {
    apiCalled = true;
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ user_id: "u" }) });
  });
  await fillConsumerRegistration(page);
  await page.locator("#registerForm button[type='submit']").click();

  // The consent checkbox is `required`, so the browser blocks submission and
  // shows its own validation bubble; the app-level message is the fallback for
  // when that attribute is absent. What must never happen is a request or a
  // dead form.
  expect(apiCalled).toBe(false);
  await expect(page.locator("#registerForm")).toBeVisible();
  await expect(page.locator("#registerConsent")).toBeVisible();
});

test("C 端注册：字段齐全并勾选同意后提交成功，请求体不含邀请码", async ({ page }) => {
  let requestBody;
  await openConsumerRegistration(page);
  await page.route("**/api/**", async (route) => {
    if (route.request().url().includes("/api/auth/invite-register")) {
      requestBody = JSON.parse(route.request().postData() || "{}");
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ user_id: "new-user-id", email: "c-side@example.com" }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });
  await fillConsumerRegistration(page);
  await page.locator("#registerConsent").check();
  await page.locator("#registerForm button[type='submit']").click();

  await expect(page.locator("#formMessage")).toContainText("账户已创建");
  expect(requestBody).toBeTruthy();
  expect(requestBody).toMatchObject({
    email: "c-side@example.com",
    password: "sixsix",
    username: "c-side-user",
    invite_code: "",
  });
  expect(requestBody.consent_version).toBeTruthy();
  expect(requestBody.terms_version).toBeTruthy();
});

const { test, expect } = require("@playwright/test");

test("policy update needs explicit consent and preserves the server version", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_API_BASE_URL = "https://policy-api.test";
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
    localStorage.setItem("zou_ui_locale", "zh-CN");
    localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", accessToken: "fixture-token", refreshToken: "fixture-refresh", userId: "fixture-user", email: "fixture@invalid.test", expiresAt: Math.floor(Date.now() / 1000) + 3600 }));
  });
  let accepted = false;
  let posted;
  await page.route("https://policy-api.test/api/account/consent", async route => {
    if (route.request().method() === "POST") { posted = route.request().postDataJSON(); accepted = true; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ accepted, privacy_policy_version: "privacy-2026-10", terms_version: "terms-2026-08" }) });
  });
  await page.route("https://supabase.test/**", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "fixture-user", email: "fixture@invalid.test", user_metadata: {} }) }));
  await page.goto("/consumer-profile.html");
  const dialog = page.locator("#policyConsentDialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("button[type=submit]")).toBeDisabled();
  await dialog.locator("input[type=checkbox]").check();
  await dialog.locator("button[type=submit]").click();
  await expect(dialog).toBeHidden();
  expect(posted).toEqual({ privacy_policy_version: "privacy-2026-10", terms_version: "terms-2026-08" });
});

for (const width of [390, 1440]) {
  test(`policy confirmation at ${width}px retries safely and works by keyboard`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript(() => {
      window.ZOUSEEKING_API_BASE_URL = "https://policy-api.test";
      localStorage.setItem("zou_ui_locale", "zh-CN");
      localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", accessToken: "fixture", refreshToken: "fixture", userId: "fixture", expiresAt: Math.floor(Date.now()/1000)+3600 }));
    });
    let unavailable = true;
    await page.route("https://policy-api.test/api/account/consent", route => route.fulfill(unavailable ? { status: 503, json: { detail: "unavailable" } } : { status: 200, json: { accepted: route.request().method() === "POST", privacy_policy_version: "privacy-2026-10", terms_version: "terms-2026-08" } }));
    await page.goto("/consumer-profile.html");
    let dialog = page.locator("#policyConsentDialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("status")).not.toBeEmpty();
    await expect(dialog.locator("button[type=submit]")).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    unavailable = false;
    await dialog.getByRole("button", { name: "重试" }).click();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("status")).toBeEmpty();
    await expect(dialog.getByRole("button", { name: "重试" })).toBeHidden();
    await dialog.locator("input").focus();
    await page.keyboard.press("Space");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    await expect(dialog).toBeHidden();
  });
}

test("account deletion stays available without accepting the policy update", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_API_BASE_URL = "https://policy-api.test";
    localStorage.setItem("zou_ui_locale", "zh-CN");
    localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", accessToken: "fixture", refreshToken: "fixture", userId: "fixture", expiresAt: Math.floor(Date.now()/1000)+3600 }));
  });
  let posts = 0;
  await page.route("https://policy-api.test/api/account/consent", route => { if (route.request().method() === "POST") posts++; return route.fulfill({ json: { accepted: false, privacy_policy_version: "privacy-2026-10", terms_version: "terms-2026-08" } }); });
  await page.goto("/consumer-profile.html");
  await page.locator("#policyConsentDialog").getByRole("button", { name: "提交删除申请" }).click();
  await expect(page.locator("#deleteAccountDialog")).toBeVisible();
  expect(posts).toBe(0);
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.locator("#deleteAccountDialog")).toBeHidden();
});

test("switching accounts discards the old checkbox and stale status response", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_API_BASE_URL = "https://policy-api.test";
    localStorage.setItem("zou_ui_locale", "zh-CN");
    localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", accessToken: "token-A", userId: "user-A", expiresAt: Math.floor(Date.now()/1000)+3600 }));
  });
  const posts = [];
  await page.route("https://policy-api.test/api/account/consent", route => {
    if (route.request().method() === "POST") posts.push(route.request().headers().authorization);
    return route.fulfill({ json: { accepted: route.request().method() === "POST", privacy_policy_version: "privacy-2026-10", terms_version: "terms-2026-08" } });
  });
  await page.goto("/consumer-profile.html");
  const dialog = page.locator("#policyConsentDialog");
  await dialog.locator("input").check();
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "supabase", accessToken: "token-B", userId: "user-B", expiresAt: Math.floor(Date.now()/1000)+3600 }));
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("input")).not.toBeChecked();
  await expect(dialog.locator("button[type=submit]")).toBeDisabled();
  expect(posts).toEqual([]);
  await dialog.locator("input").check();
  await dialog.locator("button[type=submit]").click();
  await expect(dialog).toBeHidden();
  expect(posts).toEqual(["Bearer token-B"]);
});

for (const delayedMethod of ["GET", "POST"]) {
  test(`a stale ${delayedMethod} from account A cannot dismiss account B's confirmation`, async ({ page }) => {
    await page.addInitScript(() => {
      window.ZOUSEEKING_API_BASE_URL = "https://policy-api.test";
      localStorage.setItem("zou_ui_locale", "zh-CN");
      localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", accessToken: "token-A", userId: "user-A", expiresAt: Math.floor(Date.now()/1000)+3600 }));
    });
    let release;
    let waiting = false;
    let completed = false;
    const gate = new Promise(resolve => { release = resolve; });
    await page.route("https://policy-api.test/api/account/consent", async route => {
      const stale = route.request().headers().authorization === "Bearer token-A" && route.request().method() === delayedMethod;
      if (stale) { waiting = true; await gate; }
      await route.fulfill({ json: { accepted: stale, privacy_policy_version: "privacy-2026-10", terms_version: "terms-2026-08" } });
      if (stale) completed = true;
    });
    await page.goto("/consumer-profile.html");
    const dialog = page.locator("#policyConsentDialog");
    if (delayedMethod === "POST") {
      await dialog.locator("input").check();
      await dialog.locator("button[type=submit]").click();
    }
    await expect.poll(() => waiting).toBe(true);
    await page.evaluate(() => window.ZouAuthSession.write({ provider: "supabase", accessToken: "token-B", userId: "user-B", expiresAt: Math.floor(Date.now()/1000)+3600 }));
    await expect(dialog).toBeVisible();
    release();
    await expect.poll(() => completed).toBe(true);
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("input")).not.toBeChecked();
    await expect(dialog.locator("button[type=submit]")).toBeDisabled();
  });
}

for (const action of ["logout", "Escape"]) {
  test(`declining via ${action} clears the session and returns to the consumer home`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => {
      window.ZOUSEEKING_API_BASE_URL = "https://policy-api.test";
      localStorage.setItem("zou_ui_locale", "zh-CN");
      if (location.pathname.endsWith("consumer-profile.html")) localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", accessToken: "token-A", userId: "user-A", expiresAt: Math.floor(Date.now()/1000)+3600 }));
    });
    await page.route("https://policy-api.test/api/account/consent", route => route.fulfill({ json: { accepted: false, privacy_policy_version: "privacy-2026-10", terms_version: "terms-2026-08" } }));
    await page.goto("/consumer-profile.html");
    await expect(page.locator("#policyConsentDialog")).toBeVisible();
    if (action === "Escape") await page.keyboard.press("Escape");
    else await page.locator("#policyConsentDialog").getByRole("button", { name: "退出", exact: true }).click();
    expect(errors).toEqual([]);
    await expect(page).toHaveURL(/\/consumer-home\.html$/);
    expect(await page.evaluate(() => [localStorage.getItem("zou_house_session"), localStorage.getItem("sb-zou-house-auth-token")])).toEqual([null, null]);
  });
}

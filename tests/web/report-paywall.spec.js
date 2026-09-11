const { test, expect } = require("@playwright/test");
const path = require("node:path");

const JOB_ID = "00000000-0000-0000-0000-000000000050";
const QUERY_KEY = "东京都::东京23区::渋谷区::塔楼::2026::8";

function sessionInit() {
  return `
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
    window.ZOUSEEKING_API_BASE_URL = "http://api.test";
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
    window.localStorage.setItem("zou_house_session", JSON.stringify({
      provider: "supabase",
      userId: "00000000-0000-0000-0000-000000000030",
      email: "owner@example.com",
      username: "用户 A",
      accessToken: "test-access-token",
    }));
  `;
}

function completedTask() {
  return [
    {
      id: JOB_ID,
      query_key: QUERY_KEY,
      prefecture: "东京都",
      city: "东京23区",
      ward: "渋谷区",
      asset_type: "塔楼",
      year: 2026,
      month: 8,
      status: "completed",
      generation_jobs: [{ id: JOB_ID, status: "completed", progress: 100, current_step: "完成", error_message: null }],
    },
  ];
}

test("locked report shows unlock card and never renders content", async ({ page }) => {
  await page.addInitScript(sessionInit());
  let checkoutCalls = 0;
  let unlockRequestedKey = null;

  await page.route("**/content-library.json", async (route) => {
    await route.fulfill({ path: path.resolve(__dirname, "../../data/content_library.json"), contentType: "application/json" });
  });
  await page.route("https://supabase.test/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/auth/v1/user")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000030", email: "owner@example.com", user_metadata: { username: "用户 A" } }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("http://api.test/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/my/queries") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(completedTask()) });
    }
    if (url.pathname === `/api/reports/${encodeURIComponent(QUERY_KEY)}` || url.pathname.endsWith(encodeURIComponent(QUERY_KEY))) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          locked: true,
          query_key: QUERY_KEY,
          slug: "jphouse_23ku_shibuya_tower",
          title: "东京都渋谷区塔楼成交参考",
          publish_month: "2026年［令和8年］1～3月",
          unlock_hint: "完整深度报告与导出为付费权益(risk_report_single)。购买一次解锁本账号全部报告。",
        }),
      });
    }
    if (url.pathname === "/api/billing/checkout" && route.request().method() === "POST") {
      checkoutCalls += 1;
      unlockRequestedKey = JSON.parse(route.request().postData() || "{}").query_key ?? null;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: "cs_test_1", url: "https://checkout.stripe.test/cs_test_1", product_code: "risk_report_single" }) });
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not found" }) });
  });

  await page.route("**checkout.stripe.test/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "text/html", body: "<html><body>Stripe Checkout (test)</body></html>" });
  });

  await page.goto("/mypage.html");
  await expect(page.getByRole("button", { name: "查看结果" }).first()).toBeVisible();
  await page.getByRole("button", { name: "查看结果" }).first().click();

  // Locked card: title + unlock button, no report content
  await expect(page.getByText("解锁深度报告")).toBeVisible();
  await expect(page.getByText(/本份深度报告/)).toBeVisible();
  // deep-report content strings must not appear anywhere
  const body = await page.evaluate(() => document.body.innerText);
  expect(body).not.toContain("成交均价");
  expect(body).not.toContain("国交省");

  // Unlock click posts checkout and redirects to the Stripe session
  await page.getByRole("button", { name: "解锁深度报告" }).click();
  await expect.poll(() => checkoutCalls).toBe(1);
  expect(unlockRequestedKey).toBe(QUERY_KEY);
  await page.waitForURL(/checkout\.stripe\.test/);
});

test("unlocked report renders full content (no paywall)", async ({ page }) => {
  await page.addInitScript(sessionInit());
  await page.route("**/content-library.json", async (route) => {
    await route.fulfill({ path: path.resolve(__dirname, "../../data/content_library.json"), contentType: "application/json" });
  });
  await page.route("https://supabase.test/**", async (route) => {
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("http://api.test/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/my/queries") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(completedTask()) });
    }
    if (url.pathname.endsWith(encodeURIComponent(QUERY_KEY))) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          slug: "jphouse_23ku_shibuya_tower",
          title: "东京都渋谷区塔楼成交参考",
          publish_month: "2026年［令和8年］1～3月",
          markdown: "# 深度报告\n\n成交均价参考(国交省取引数据)。",
          xhs_content: "深度报告",
          rental: [],
          sale: [{ layout: "1LDK", amount_jpy: "约10,257万日元", amount_yen: 102570000, data_class: "scraped_aggregate" }],
          summary: { title: "总而言之", line: "1LDK 约10,257万日元" },
          images: [],
          data_sources: [],
          raw_record: {},
        }),
      });
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not found" }) });
  });

  await page.goto("/mypage.html");
  await expect(page.getByRole("button", { name: "查看结果" }).first()).toBeVisible();
  await page.getByRole("button", { name: "查看结果" }).first().click();
  await expect(page.getByText("解锁深度报告")).not.toBeVisible();
  await expect(page.getByText("成交均价参考")).toBeVisible();
});

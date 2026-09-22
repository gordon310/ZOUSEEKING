const { test, expect } = require("@playwright/test");

const trendPayload = {
  status: "ok", period_count: 2, asset_type: "公寓", prefecture: "东京都", city: "港区", ward: null,
  excluded_periods: [{ period: "2025Q3", reason: "insufficient_sample", sample_size: 4 }],
  comparability: { consistent: true, inconsistent_dimensions: [], dimensions: { unit: ["JPY/sqm"], asset_type: ["公寓"] } },
  periods: [
    { period: "2025Q4", sample_size: 5, mean_unit_price_jpy_per_sqm: 1000000, median_unit_price_jpy_per_sqm: 990000, p25: 900000, p75: 1100000, source_url: "https://fixtures.invalid/q4", data_class: "synthetic_fixture", retrieved_at: "2026-09-22T00:00:00+00:00", source_period: "2025Q4", transformation_version: "fixture-v1", rights_status: "not_applicable", rights_confirmed: "not_applicable", aggregation_method: "mean_median_quartiles", missing_value_policy: "exclude_missing_or_nonpositive_unit_price", limitations: "Fixture only.", unit: "JPY/sqm" },
    { period: "2026Q1", sample_size: 6, mean_unit_price_jpy_per_sqm: 1200000, median_unit_price_jpy_per_sqm: 1180000, p25: 1100000, p75: 1300000, source_url: "https://fixtures.invalid/q1", data_class: "synthetic_fixture", retrieved_at: "2026-09-22T00:00:00+00:00", source_period: "2026Q1", transformation_version: "fixture-v1", rights_status: "not_applicable", rights_confirmed: "not_applicable", aggregation_method: "mean_median_quartiles", missing_value_policy: "exclude_missing_or_nonpositive_unit_price", limitations: "Fixture only.", unit: "JPY/sqm" },
  ],
};

const demoSession = { provider: "demo", username: "Member", email: "member@example.test", userId: "member-1", accessToken: "test-token" };

test("trend view renders an accessible summary and semantic table without console errors", async ({ page }) => {
  const browserErrors = [];
  const apiRequests = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") browserErrors.push(message.text()); });
  page.on("request", (request) => { if (request.url().includes("/api/")) apiRequests.push(request.url()); });
  await page.addInitScript((session) => {
    window.ZOUSEEKING_API_BASE_URL = "https://api.test";
    window.ZOUSEEKING_RELEASE_SCOPE = Object.freeze({ phase: "development", businessOperations: true, adminOperations: false });
    localStorage.setItem("zou_house_session", JSON.stringify(session));
  }, demoSession);
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    return route.fulfill({ json: url.pathname === "/api/org/region-stats/trend" ? trendPayload : {} });
  });
  await page.goto("/data-query.html");
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  expect(await page.evaluate(() => window.ZouAuthSession.read())).toMatchObject({ provider: "demo", username: "Member" });
  expect(await page.evaluate(async () => window.ZouAuthSession.ensureValidSession(window.ZouAuthSession.read()))).toMatchObject({ provider: "demo" });
  await page.getByLabel("趋势").check();
  await page.locator("#regionStatsForm").evaluate((form) => form.requestSubmit());

  await expect.poll(() => apiRequests).toHaveLength(1);
  expect(apiRequests[0]).toContain("/api/org/region-stats/trend?");
  await expect(page.getByTestId("region-stats-trend-summary")).toContainText("2 个可比期次");
  const table = page.getByTestId("region-stats-trend-table");
  await expect(table).toContainText("2025年 Q4");
  await expect(table).toContainText("2026年 Q1");
  await expect(table).toContainText("5");
  await expect(table).toContainText("https://fixtures.invalid/q4");
  expect(browserErrors).toEqual([]);
});

test("trend view shows explicit insufficient-period state instead of an empty chart", async ({ page }) => {
  await page.addInitScript((session) => {
    window.ZOUSEEKING_API_BASE_URL = "https://api.test";
    window.ZOUSEEKING_RELEASE_SCOPE = Object.freeze({ phase: "development", businessOperations: true, adminOperations: false });
    localStorage.setItem("zou_house_session", JSON.stringify(session));
  }, demoSession);
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const payload = { ...trendPayload, status: "insufficient_periods", period_count: 1, periods: [] };
    return route.fulfill({ json: url.pathname === "/api/org/region-stats/trend" ? payload : {} });
  });
  await page.goto("/data-query.html");
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.getByLabel("趋势").check();
  await page.locator("#regionStatsForm").evaluate((form) => form.requestSubmit());
  await expect(page.locator("#regionStatsResult")).toContainText("至少需要 2 个可比期次");
  await expect(page.getByTestId("region-stats-trend-table")).toHaveCount(0);
});

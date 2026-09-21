const { test, expect } = require("@playwright/test");

const demoSession = {
  username: "Demo User",
  email: "demo@example.com",
  provider: "demo",
  accessToken: "test-token",
};

const regionStatsFixture = Object.freeze({
  prefecture: "夹具都道府县",
  city: "夹具特征市",
  asset_type: "公寓",
  period: "2026Q2",
  mean_unit_price_jpy_per_sqm: 1234567,
  median_unit_price_jpy_per_sqm: 1200000,
  p25: 1100000,
  p75: 1300000,
  data_class: "verified_observation",
  source_url: "https://fixtures.invalid/region-stats-provenance",
  retrieved_at: "2026-09-21T12:34:56.000Z",
  source_period: "fixture-period-2026Q2",
  transformation_version: "fixture-transform-v1",
  rights_status: "verified",
  rights_confirmed: "yes",
  sample_size: 7,
  aggregation_method: "fixture_mean_median_quartiles",
  missing_value_policy: "fixture_excludes_missing_prices",
  limitations: "Fixture-only limitation for provenance rendering.",
  unit: "JPY/sqm",
});

test("region metric provenance line is assembled from API response fields", async ({ page }) => {
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(`console: ${message.text()}`);
  });
  await page.addInitScript((session) => {
    window.ZOUSEEKING_API_BASE_URL = "https://api.test";
    window.ZOUSEEKING_RELEASE_SCOPE = Object.freeze({
      phase: "development",
      businessOperations: true,
      adminOperations: false,
    });
    localStorage.setItem("zou_house_session", JSON.stringify(session));
  }, demoSession);
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/org/region-stats") {
      return route.fulfill({ json: regionStatsFixture });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto("/data-query.html");
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.locator("#regionStatsForm").evaluate((form) => form.requestSubmit());

  const provenance = page.getByTestId("region-stats-provenance");
  await expect(provenance).toContainText(regionStatsFixture.source_url);
  await expect(provenance).toContainText(regionStatsFixture.source_period);
  await expect(provenance).toContainText(regionStatsFixture.aggregation_method);
  await expect(provenance).toContainText(regionStatsFixture.missing_value_policy);
  await expect(page.locator("#regionStatsResult")).toContainText("1,234,567");
  expect(browserErrors).toEqual([]);
});

const { test, expect } = require("@playwright/test");

test("region metric provenance line is assembled from API response fields", async ({ page }) => {
  await page.goto("/index.html");
  const source = await page.evaluate(() => fetch("app.js").then((response) => response.text()));
  expect(source).toContain("data.source_url");
  expect(source).toContain("data.source_period");
  expect(source).toContain("data.aggregation_method");
  expect(source).toContain('data-testid="region-stats-provenance"');
});

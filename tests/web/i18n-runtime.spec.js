const { test, expect } = require("@playwright/test");

test("browser runtime preserves every hand-written zh-Hant dynamic translation", async ({ page }) => {
  await page.goto("/data-query.html?lang=zh-Hant");
  const mismatches = await page.evaluate(() => Object.entries(window.__additionalI18n)
    .filter(([, values]) => Object.prototype.hasOwnProperty.call(values, "zh-Hant"))
    .filter(([key, values]) => window.ZouI18n.t(key) !== values["zh-Hant"])
    .map(([key]) => key));
  expect(mismatches).toEqual([]);
});

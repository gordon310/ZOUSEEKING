const { test, expect } = require("@playwright/test");

test("区域成交价统计成功态展示真实口径与出典", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_API_BASE_URL = "https://api.test";
  });
  const successPayload = {
      status: "ok", sample_size: 553, median_unit_price_jpy_per_sqm: 1800000,
      p25: 1266666.67, p75: 2640000, period: "2025Q1", asset_type: "公寓",
      sources: [{ name: "国土交通省 不動産情報ライブラリ", url: "https://www.reinfolib.mlit.go.jp/realEstatePrices/" }],
      license: { name: "PDL1.0" }, limitations: "参考信息", data_class: "scraped_aggregate",
      rent_sale_ratio: { available: false, reason: "租金数据未授权" },
  };
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "demo", username: "Member", email: "member@example.test", userId: "member-1" }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.evaluate((payload) => { window.fetch = async () => new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }); }, successPayload);
  await page.evaluate(() => window.ZouRegionStats.load({ preventDefault() {} }));
  await expect(page.locator("#regionStatsResult")).toContainText("1,800,000");
  await expect(page.locator("#regionStatsResult")).toContainText("出典");
  await expect(page.locator("#regionStatsResult")).toContainText("租售比");
  await expect(page.locator("#regionStatsResult")).not.toContainText("scraped_aggregate");
});

test("区域成交价统计样本不足态不显示数字", async ({ page }) => {
  await page.addInitScript(() => { window.ZOUSEEKING_API_BASE_URL = "https://api.test"; });
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "demo", username: "Member", email: "member@example.test", userId: "member-1" }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.evaluate(() => { window.fetch = async () => new Response(JSON.stringify({ status: "insufficient_sample", sample_size: 4 }), { status: 200, headers: { "Content-Type": "application/json" } }); });
  await page.evaluate(() => window.ZouRegionStats.load({ preventDefault() {} }));
  await expect(page.locator("#regionStatsResult")).toContainText("样本不足");
  await expect(page.locator("#regionStatsResult")).not.toContainText("中位㎡单价");
});

test("塔楼统计显示口径说明且不泄露内部标识", async ({ page }) => {
  await page.addInitScript(() => { window.ZOUSEEKING_API_BASE_URL = "https://api.test"; });
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "demo", username: "Member", email: "member@example.test", userId: "member-1" }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.selectOption("#statsAssetType", { label: "塔楼" });
  await page.evaluate(() => window.fetch = async () => new Response(JSON.stringify({
    status: "ok", sample_size: 5, median_unit_price_jpy_per_sqm: 300000,
    p25: 200000, p75: 400000, disclosure: { code: "tower_merged_into_apartment" },
  }), { status: 200, headers: { "Content-Type": "application/json" } }));
  await page.evaluate(() => window.ZouRegionStats.load({ preventDefault() {} }));
  await expect(page.locator("#regionStatsResult")).toContainText("官方数据未区分塔楼与公寓");
  await expect(page.locator("#regionStatsResult")).not.toContainText("tower_merged_into_apartment");
});

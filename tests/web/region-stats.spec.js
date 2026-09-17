const { test, expect } = require("@playwright/test");

test("区域成交价统计表单选项全部来自 field-options 词表", async ({ page }) => {
  await page.goto("/data-query.html");
  const options = await page.evaluate(async () => fetch("field-options.json").then((response) => response.json()));
  const values = await page.evaluate(() => Object.fromEntries(
    ["statsPrefecture", "statsCity", "statsAssetType", "statsYear", "statsQuarter"].map((id) => [
      id,
      [...document.querySelectorAll(`#${id} option`)].map((option) => option.value),
    ]),
  ));
  expect(values.statsPrefecture.every((value) => options.prefectures.includes(value))).toBe(true);
  const selectedPrefecture = await page.locator("#statsPrefecture").inputValue();
  expect(values.statsCity.every((value) => options.cities[selectedPrefecture].includes(value))).toBe(true);
  expect(values.statsAssetType.every((value) => options.assetTypes.includes(value))).toBe(true);
  expect(values.statsYear.every((value) => options.years.includes(value))).toBe(true);
  expect(values.statsQuarter.every((value) => options.quarters.includes(value))).toBe(true);
});

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

test("区域成交价统计将 403 显示为权限提示而不是暂时失败", async ({ page }) => {
  await page.addInitScript(() => { window.ZOUSEEKING_API_BASE_URL = "https://api.test"; });
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "demo", username: "Member", email: "member@example.test", userId: "member-1" }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.evaluate(() => {
    window.fetch = async () => new Response(JSON.stringify({ error: { code: "org_forbidden", message: "无权访问" } }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    });
  });
  await page.evaluate(() => window.ZouRegionStats.load({ preventDefault() {} }));
  await expect(page.locator("#regionStatsResult")).toContainText("当前账户没有机构统计权限");
  await expect(page.locator("#regionStatsResult")).not.toContainText("统计暂时无法读取");
});

test("区域成交价统计将 500 显示为暂时失败", async ({ page }) => {
  await page.addInitScript(() => { window.ZOUSEEKING_API_BASE_URL = "https://api.test"; });
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "demo", username: "Member", email: "member@example.test", userId: "member-1" }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.evaluate(() => {
    window.fetch = async () => new Response("服务不可用", { status: 500 });
  });
  await page.evaluate(() => window.ZouRegionStats.load({ preventDefault() {} }));
  await expect(page.locator("#regionStatsResult")).toContainText("统计暂时无法读取");
});

test("物件查询的来源失败只显示本地化安全文案", async ({ page }) => {
  await page.addInitScript(() => { window.ZOUSEEKING_API_BASE_URL = "https://api.test"; });
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({
    provider: "supabase", username: "Member", email: "member@example.test", userId: "member-1", accessToken: "test-token", refreshToken: "test-refresh",
  }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.evaluate(() => {
    window.fetch = async (url) => {
      if (String(url).includes("/api/query")) {
        return new Response(JSON.stringify({ job_id: "job-1", status: "pending", cached: false, title: "测试", query_key: "test", report: null }), { status: 200 });
      }
      if (String(url).includes("/api/jobs/job-1")) {
        return new Response(JSON.stringify({
          job_id: "job-1", status: "failed", progress: 100, current_step: "失败",
          error: { code: "market_source_unavailable", message: "市场数据源暂时不可用，请稍后重试。" },
        }), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    };
    for (const select of document.querySelectorAll("#queryForm select")) select.disabled = false;
    const prefecture = document.querySelector("#prefectureSelect");
    prefecture.selectedIndex = 1;
    prefecture.dispatchEvent(new Event("change", { bubbles: true }));
    const city = document.querySelector("#citySelect");
    city.selectedIndex = 1;
    city.dispatchEvent(new Event("change", { bubbles: true }));
    document.querySelector("#assetTypeSelect").selectedIndex = 1;
    document.querySelector("#yearSelect").selectedIndex = 1;
    document.querySelector("#monthSelect").selectedIndex = 1;
    document.querySelector("#queryForm").requestSubmit();
  });
  await expect(page.locator("#formMessage")).toContainText("市场数据源暂时不可用，请稍后重试");
  await expect(page.locator("body")).not.toContainText("market_source_unavailable");
  await expect(page.locator("body")).not.toContainText("no rights_confirmed");
});

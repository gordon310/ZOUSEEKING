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
    status: "ok", sample_size: 552, mean_unit_price_jpy_per_sqm: 1794736.84, median_unit_price_jpy_per_sqm: 1800000,
      p25: 1263636.365, p75: 2646666.668, period: "2025Q1", asset_type: "公寓",
      sources: [{ name: "国土交通省 不動産情報ライブラリ", url: "https://www.reinfolib.mlit.go.jp/realEstatePrices/" }],
      license: { name: "PDL1.0" }, limitations: "参考信息", data_class: "scraped_aggregate",
      rent_reference: { rent_jpy_per_sqm_month: 1809, scope_label: "借家(専用住宅)・共同住宅・非木造", survey_label: "令和5年(2023)", survey_year: 2023, geo_level: "city", geo_level_label: "市区町村", source_key: "estate_housing_land_122_5", source_label: "令和5年住宅・土地統計調査 第122-5表", source_url: "https://www.e-stat.go.jp/", license_label: "e-Stat" },
      monthly_rent_reference: { rent_jpy_per_sqm_month: 1260, observed_month: "2026-08", source_label: "小売物価統計調査(動向編) 2026年8月", source_url: "https://www.e-stat.go.jp/", license_label: "e-Stat" },
      rent_to_price_ratio: { gross_value: 0.012, formula_label: "formula", numerator_label: "rent", denominator_label: "price", survey_label: "令和5年(2023)", geo_level: "city" },
  };
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "demo", username: "Member", email: "member@example.test", userId: "member-1" }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.evaluate((payload) => { window.fetch = async () => new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }); }, successPayload);
  await page.evaluate(() => window.ZouRegionStats.load({ preventDefault() {} }));
  const statsResult = page.locator("#regionStatsResult");
  await expect(statsResult).toContainText("东京都 港区 · 公寓 · 2025年 Q1");
  await expect(statsResult).toContainText("均价 约 179.5 万円/㎡");
  await expect(statsResult).toContainText("中位数 约 180.0 万円/㎡");
  await expect(statsResult).toContainText("主力成交价带 126.4 〜 264.7 万円/㎡");
  await expect(statsResult).not.toContainText("低于此带 = 相对便宜,高于此带 = 相对偏贵(按官方成交四分位计算)");
  await expect(statsResult).toContainText("均价 = 全部成交的平均值,高价房源会把均价拉高;中位数 = 成交价排序后取中间,更能代表典型行情。");
  await expect(statsResult).toContainText("552 笔官方成交记录");
  await expect(statsResult).toContainText("精确值:均价 1,794,737 円/㎡ · 中位数 1,800,000 円/㎡ · 区间 1,263,636 〜 2,646,667 円/㎡");
  await expect(statsResult.locator(".stats-summary")).not.toContainText(/\d+\.\d{2,}/);
  await expect(statsResult.locator(".stats-exact")).not.toContainText(/\d+\.\d{2,}/);
  await expect(page.locator("#regionStatsResult")).toContainText("出典");
  await expect(page.locator("#regionStatsResult")).toContainText("租售比");
  await expect(statsResult).toContainText("租售比(毛) 约 1.20%");
  await expect(statsResult).toContainText("官方家賃 1,809 円/㎡/月（市区町村・令和5年(2023)）");
  await expect(statsResult).toContainText("年家賃 21,708 円/㎡/年（1,809 × 12）");
  await expect(statsResult).toContainText("㎡均价 1,794,737 円/㎡（官方成交均值・552 笔）");
  await expect(statsResult).toContainText("计算式 21,708 ÷ 1,794,737 = 1.20%");
  await expect(statsResult).toContainText("官方家賃月度动向：1,260 円/㎡/月（2026年8月・都市别口径）");
  await expect(statsResult).toContainText("按官方家賃（令和5年(2023)・借家(専用住宅)・共同住宅・非木造）与本市㎡均价计算");
  await expect(statsResult).toContainText("说明 毛回报；不含管理费/修缮费/空置等费用");
  await expect(statsResult).not.toContainText("家賃基准为 令和5年(2023) 官方调查");
  expect(await statsResult.getByText(/不含管理费\/修缮费\/空置等费用/).count()).toBe(1);
  await expect(statsResult).toContainText("政府統計の総合窓口(e-Stat)(https://www.e-stat.go.jp/)(加工して作成)");
  await expect(page.locator("#regionStatsResult")).not.toContainText("scraped_aggregate");
});

test("区域成交价统计租金回落到都道府县时明确标注口径", async ({ page }) => {
  await page.addInitScript(() => { window.ZOUSEEKING_API_BASE_URL = "https://api.test"; });
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "demo", username: "Member", email: "member@example.test", userId: "member-1" }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.evaluate(() => window.fetch = async () => new Response(JSON.stringify({
    status: "ok", sample_size: 5, mean_unit_price_jpy_per_sqm: 1200000, median_unit_price_jpy_per_sqm: 1200000, p25: 1000000, p75: 1400000,
    period: "2025Q1", asset_type: "公寓", rent_reference: { rent_jpy_per_sqm_month: 1223, scope_label: "民営借家・借家(専用住宅)", survey_label: "令和5年(2023)", geo_level: "prefecture", geo_level_label: "都道府县" },
    rent_to_price_ratio: { gross_value: 0.01223, geo_level: "prefecture" },
  }), { status: 200, headers: { "Content-Type": "application/json" } }));
  await page.evaluate(() => window.ZouRegionStats.load({ preventDefault() {} }));
  await expect(page.locator("#regionStatsResult")).toContainText("按所在都道府县口径（该市区町村无官方数据）");
  expect(await page.locator("#regionStatsResult").getByText(/不含管理费\/修缮费\/空置等费用/).count()).toBe(1);
  await expect(page.locator("#regionStatsResult")).toContainText("官方家賃 1,223 円/㎡/月（都道府县・令和5年(2023)）");
});

test("区域成交价统计四语言文案键完整且没有内部枚举", async ({ page }) => {
  await page.goto("/data-query.html");
  const locales = await page.evaluate(() => Object.fromEntries(["zh-CN", "zh-Hant", "en", "ja"].map((locale) => {
    localStorage.setItem("zou_ui_locale", locale);
    window.ZouI18n?.setLocale?.(locale);
    const dictionary = window.__additionalI18n || {};
    return [locale, Object.fromEntries(Object.entries(dictionary).filter(([key]) => key.startsWith("regionStats.")))];
  })));
  const keys = Object.keys(locales["zh-CN"]);
  expect(keys.length).toBeGreaterThan(0);
  for (const locale of ["zh-CN", "zh-Hant", "en", "ja"]) {
    expect(Object.keys(locales[locale]).sort()).toEqual(keys.sort());
    for (const value of Object.values(locales[locale])) {
      for (const text of Object.values(value)) expect(text).not.toMatch(/\b(?:scraped_aggregate|insufficient_sample|tower_merged_into_apartment)\b/);
    }
  }
  expect(locales["zh-Hant"]["regionStats.insufficient"]["zh-Hant"]).toContain("數據");
  expect(locales["zh-CN"]["regionStats.rentDetailFormula"]["zh-CN"]).toContain("{annualRent}");
});

test("区域成交价统计样本不足态不显示数字", async ({ page }) => {
  await page.addInitScript(() => { window.ZOUSEEKING_API_BASE_URL = "https://api.test"; });
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "demo", username: "Member", email: "member@example.test", userId: "member-1" }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await page.evaluate(() => { window.fetch = async () => new Response(JSON.stringify({ status: "insufficient_sample", sample_size: 4 }), { status: 200, headers: { "Content-Type": "application/json" } }); });
  await page.evaluate(() => window.ZouRegionStats.load({ preventDefault() {} }));
  await expect(page.locator("#regionStatsResult")).toContainText("官方成交记录不足 5 笔");
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

test("物件查询未命中提示使用业务措辞", async ({ page }) => {
  await page.goto("/data-query.html");
  await page.evaluate(() => window.ZouAuthSession.write({ provider: "demo", username: "Member", email: "member@example.test", userId: "member-1" }));
  await page.waitForFunction(() => document.body.classList.contains("auth-ready"));
  await expect(page.locator("#queryHint")).toContainText("未命中的条件会先记录下来");
  await expect(page.locator("#queryHint")).not.toContainText(/Supabase|JPHOUSE|采集器/);
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

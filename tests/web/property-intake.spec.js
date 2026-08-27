const { test, expect } = require("@playwright/test");

const SESSION_ID = "00000000-0000-0000-0000-000000000040";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/intake/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let body = {};
    if (request.postData()) {
      try {
        body = JSON.parse(request.postData());
      } catch {
        body = {};
      }
    }

    if (path === "/api/intake/sessions" && request.method() === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: SESSION_ID,
          session_token: "test-session-token",
          expires_at: "2026-08-26T00:00:00Z",
          expires_in_seconds: 86400,
        }),
      });
      return;
    }

    if (path.endsWith("/preview") && request.method() === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: SESSION_ID,
          completeness: {
            identity: {
              confirmed: 2,
              total: 4,
              percent: 50,
              status: "partial",
              missing: ["building_name", "building_year"],
              missing_critical: [],
              conflicts: [],
            },
            price_cost: {
              confirmed: 1,
              total: 3,
              percent: 33,
              status: "partial",
              missing: ["management_fee_jpy", "repair_reserve_jpy"],
              missing_critical: [],
              conflicts: [],
            },
            yield: { confirmed: 0, total: 3, percent: 0, status: "empty", missing: [], missing_critical: [], conflicts: [] },
            building_management: { confirmed: 0, total: 3, percent: 0, status: "empty", missing: [], missing_critical: [], conflicts: [] },
            legal_transaction: {
              confirmed: 0,
              total: 2,
              percent: 0,
              status: "insufficient_data",
              missing: ["land_right", "land_share"],
              missing_critical: ["land_right"],
              conflicts: [],
            },
            source_trust: { confirmed: 1, total: 4, percent: 25, status: "partial", missing: [], missing_critical: [], conflicts: [] },
          },
          acquisition_costs: {
            status: "rules_not_loaded",
            estimated_total_jpy: null,
            items: ["中介手续费", "不动产取得税", "登记许可税和司法书士费用"],
          },
          risk_summary: { level: "data_only", count: 1, items: ["法律与交易资料仍不完整。"] },
          comparable_status: "not_checked",
          calculation_version: "free-preview-v1",
        }),
      });
      return;
    }

    if (path.endsWith("/fields/asking_price_jpy") || path.endsWith("/fields/area_sqm")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          field_name: body.field_name || path.split("/").pop(),
          value: body.value,
          unit: path.endsWith("asking_price_jpy") ? "JPY" : "sqm",
          confirmation_status: body.confirmation_status || "confirmed",
          confidence: "unreviewed",
          locator: "用户手动填写",
        }),
      });
      return;
    }

    if (path.endsWith("/convert") && request.method() === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          owner_user_id: "00000000-0000-0000-0000-000000000030",
          property_id: "00000000-0000-0000-0000-000000000020",
        }),
      });
      return;
    }

    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ input_id: "00000000-0000-0000-0000-000000000041", processing_status: "manual_review" }),
    });
  });
});

test("anonymous user reaches free preview on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/property-analysis.html");
  await expect(page.locator(".intake-progress li")).toHaveCount(5);
  await page.getByLabel("投资出租").check();
  await page.getByLabel("房源链接或说明").fill("大阪市北区，售价3500万日元，45.2平方米");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByLabel("专有面积（平方米）").fill("45.2");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await expect(page.getByRole("heading", { name: "免费项目预览" })).toBeVisible();
  await expect(page.getByText("法律与交易资料")).toBeVisible();
});

test("upload error keeps entered fields and focuses message", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.getByLabel("房源链接或说明").fill("这段资料应该保留");
  await page.setInputFiles("#propertyFiles", {
    name: "bad.exe",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("bad"),
  });
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await expect(page.getByRole("alert")).toContainText("仅支持 PDF、JPG、PNG");
  await expect(page.getByLabel("房源链接或说明")).toHaveValue("这段资料应该保留");
  await expect(page.getByRole("alert")).toBeFocused();
});

test("existing Supabase auth session can save the preview", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.getByLabel("房源链接或说明").fill("大阪市北区，售价3500万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await page.evaluate(() => {
    window.localStorage.setItem(
      "zou_house_session",
      JSON.stringify({ provider: "supabase", accessToken: "test-access-token" }),
    );
  });
  await page.getByRole("button", { name: "登录后保存项目" }).click();
  await expect(page.getByRole("button", { name: "项目已保存" })).toBeDisabled();
  await expect(page.locator("[data-stage='save']")).toHaveAttribute("aria-current", "step");
});

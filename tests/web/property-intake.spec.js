const { test, expect } = require("@playwright/test");

const SESSION_ID = "00000000-0000-0000-0000-000000000040";

async function fillLocation(page, { prefecture = "大阪府", city = "大阪市", ward = "北区" } = {}) {
  await page.getByLabel("都道府县").selectOption(prefecture);
  await page.getByLabel("市").selectOption(city);
  await page.getByLabel("区").selectOption(ward);
}

test.beforeEach(async ({ page }, testInfo) => {
  if (!testInfo.title.startsWith("staging intake")) {
    await page.addInitScript(() => {
      window.ZOUSEEKING_API_BASE_URL = "http://127.0.0.1:8787";
      window.ZOUSEEKING_RELEASE_SCOPE = { phase: "development", businessOperations: true, adminOperations: true };
    });
  }
  let convertAttempts = 0;
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
      const previewReady = new URL(page.url()).searchParams.get("ready") === "1";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: SESSION_ID,
          query_key: "大阪府::大阪市::北区::塔楼::2026::8",
          report_status: previewReady ? "full_report" : "insufficient_data",
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

    if (path.endsWith("/location") && request.method() === "PUT") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          latitude: 34.7025,
          longitude: 135.4959,
          accuracy_m: 18.5,
          captured_at: "2026-08-28T03:30:00Z",
          location_source: "device_geolocation",
          address_candidate: "大阪府大阪市北区梅田",
          address_source: "gsi_reverse_geocoder",
          address_precision: "town",
        }),
      });
      return;
    }

    if (path.includes("/fields/") && request.method() === "PUT") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          field_name: body.field_name || path.split("/").pop(),
          value: body.value,
          unit: body.field_name === "asking_price_jpy" ? "JPY" : body.field_name === "area_sqm" ? "sqm" : null,
          confirmation_status: body.confirmation_status || "confirmed",
          confidence: "unreviewed",
          locator: body.locator || "用户手动填写",
        }),
      });
      return;
    }

    if (path.endsWith("/convert") && request.method() === "POST") {
      convertAttempts += 1;
      if (new URL(page.url()).searchParams.get("duplicate") === "1" && convertAttempts === 1) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail: {
              code: "duplicate_address",
              message: "同一地址已有调查记录，请手工修改记录名称。",
            },
          }),
        });
        return;
      }
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

test("staging intake page points to the deployed FastAPI", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await expect.poll(() => page.evaluate(() => window.ZOUSEEKING_API_BASE_URL)).toBe(
    "https://zouseeking-api-staging.onrender.com",
  );
});

test("anonymous user reaches free preview on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/property-analysis.html");
  await expect(page.locator(".intake-progress li")).toHaveCount(5);
  await page.getByLabel("投资出租").check();
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元，45.2平方米");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByLabel("专有面积（平方米）").fill("45.2");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await expect(page.locator("#previewStep").getByRole("heading", { name: "免费项目预览", exact: true })).toBeVisible();
  await expect(page.locator("#previewStep").getByText("法律与交易资料", { exact: true })).toBeVisible();
  await expect(page.locator("#previewStep")).not.toContainText("land_right");
  await expect(page.locator("#previewStep")).not.toContainText("insufficient_data");
  await expect(page.locator("#previewStep")).toContainText("土地权利");
  await expect(page.locator("#reportLink")).toHaveClass(/\bhidden\b/);
  await expect(page.locator("#savedProjectLink")).toHaveClass(/\bhidden\b/);
  await expect(page.locator("#previewStep .save-project a")).toHaveCount(1);
  await expect(page.locator("#saveProjectButton")).toHaveText("登录后保存项目");
});

test("authenticated preview sends the Supabase access token", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_AUTH_SESSION = {
      provider: "supabase",
      username: "temporary-preview-test",
      accessToken: "preview-access-token",
      refreshToken: "preview-refresh-token",
    };
    window.localStorage.setItem("sb-zou-house-auth-token", JSON.stringify({
      access_token: "preview-access-token",
      refresh_token: "preview-refresh-token",
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: "temporary-preview-test" },
    }));
  });
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.setInputFiles("#propertyPhotos", { name: "house.jpg", mimeType: "image/jpeg", buffer: Buffer.from("photo") });
  await page.getByLabel("售价（日元）").fill("35000000");
  const previewRequest = page.waitForRequest((request) => request.url().includes(`/api/intake/sessions/${SESSION_ID}/preview`));
  await page.getByRole("button", { name: "生成免费预览" }).click();
  const request = await previewRequest;
  await expect(page.locator("#previewStep").getByRole("heading", { name: "免费项目预览", exact: true })).toBeVisible();
  expect(request.headers().authorization).toBe("Bearer preview-access-token");
});

test("traditional Chinese extraction copy replaces every fields placeholder", async ({ page }) => {
  await page.goto("/property-analysis.html?lang=zh-Hant");
  await page.getByLabel("物件類型 / 房型").selectOption("tower");
  await page.getByLabel("都道府縣").selectOption("大阪府");
  await page.getByLabel("市").selectOption("大阪市");
  await page.locator("#ward").selectOption("北区");
  await page.locator("#propertySource").fill("售價3500萬日圓");
  await page.getByRole("button", { name: "開始整理資料" }).click();
  await expect(page.locator("#extractionHelp")).toContainText("專有面積");
  await expect(page.locator("#extractionHelp")).toContainText("售價");
  await expect(page.locator("#extractionHelp")).not.toContainText("{fields}");
});

test("extraction placeholders are replaced in every supported locale", async ({ page }) => {
  for (const locale of ["zh-CN", "zh-Hant", "en", "ja"]) {
    await page.goto(`/property-analysis.html?lang=${locale}`);
    await page.evaluate(() => sessionStorage.clear());
    await page.reload();
    await page.locator("#assetType").selectOption("tower");
    await page.locator("#prefecture").selectOption("大阪府");
    await page.locator("#city").selectOption("大阪市");
    await page.locator("#ward").selectOption("北区");
    await page.locator("#propertySource").fill("售价3500万日元");
    await page.locator("#submitButton").click();
    await expect(page.locator("#confirmStep")).toBeVisible();
    await expect(page.locator("#extractionHelp")).not.toContainText("{fields}");
  }
});

test("anonymous save keeps the C-end login flow on the consumer account page", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.setInputFiles("#propertyPhotos", { name: "house.jpg", mimeType: "image/jpeg", buffer: Buffer.from("photo") });
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByLabel("专有面积（平方米）").fill("45.2");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await expect(page.locator("#saveProjectButton")).toHaveText("登录后保存项目");
  await page.locator("#saveProjectButton").click();

  await expect(page).toHaveURL(/\/profile\.html\?role=consumer#accountPanel$/);
  await expect(page).toHaveTitle("账户资料｜小象避坑 ZOUBEACON");
});

test("ready report is the only next action after saving", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("zou_house_session", JSON.stringify({
      provider: "supabase", username: "Gordon", accessToken: "test-access-token", refreshToken: "test-refresh-token",
    }));
  });
  await page.goto("/property-analysis.html?ready=1&lang=zh-CN");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await expect(page.locator("#reportLink")).toHaveAttribute("href", /report\.html\?key=.*&lang=zh-CN/);
  await page.locator("#saveProjectButton").click();
  await expect(page.locator("#saveProjectButton")).toHaveText("查看报告");
  await expect(page.locator("#saveProjectButton")).toBeEnabled();
  await expect(page.locator("#savedProjectLink")).toHaveClass(/\bhidden\b/);
  await expect(page.locator("#previewStep .save-project a")).toHaveCount(1);
});

test("text intake extracts price, area, and address without borrowing unrelated numbers", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.getByLabel("物件链接或说明").fill("林寺2-5-22 售价 5200万日元 面积110平方");
  await page.getByRole("button", { name: "开始整理资料" }).click();

  await expect(page.getByLabel("售价（日元）")).toHaveValue("52000000");
  await expect(page.getByLabel("专有面积（平方米）")).toHaveValue("110");
  await expect(page.getByLabel("完整地址")).toHaveValue("林寺2-5-22");
  await expect(page.locator("#extractionHelp")).toContainText("已从文字资料识别");
});

test("ZOUBEACON shell switches between desktop rail and mobile flow navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/property-analysis.html");
  await expect(page.getByRole("link", { name: /小象避坑/ })).toBeVisible();
  await expect(page.getByText("ZOUBEACON", { exact: true })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "分析进度" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "流程导航" })).toBeHidden();
  await expect(page.locator(".mobile-flow-nav")).toBeHidden();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("complementary", { name: "分析进度" })).toBeHidden();
  await expect(page.locator(".mobile-flow-nav")).toBeVisible();
});

test("desktop progress rail reflects purpose and source input", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/property-analysis.html");
  await expect(page.getByTestId("completion-count")).toHaveText("已完成 1/6 项");

  await page.getByLabel("投资出租").check();
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元，45.2平方米");

  await expect(page.getByTestId("completion-count")).toHaveText("已完成 3/6 项");
  await expect(page.getByTestId("purpose-summary")).toHaveText("投资出租");
  await expect(page.getByTestId("source-summary")).toContainText("大阪市北区");
});

test("upload error keeps entered fields and focuses message", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件链接或说明").fill("这段资料应该保留");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.setInputFiles("#propertyFiles", {
    name: "bad.exe",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("bad"),
  });
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await expect(page.getByRole("alert")).toContainText("仅支持 PDF、JPG、PNG");
  await expect(page.getByLabel("物件链接或说明")).toHaveValue("这段资料应该保留");
  await expect(page.getByRole("alert")).toBeFocused();
});

test("photo capture requests location and fills a candidate address", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_AUTH_SESSION = { provider: "supabase", username: "test-user", refreshToken: "test-refresh-token", accessToken: "test-access-token" };
  });
  await page.route("**/api/recognition", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ location: { prefecture: "大阪府", city: "大阪市", ward: "北区", address: "大阪府大阪市北区梅田" }, location_reason: "照片位置识别", listing: null }) });
  });
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: {
        getCurrentPosition(success) {
          success({
            coords: { latitude: 34.7025, longitude: 135.4959, accuracy: 18.5 },
            timestamp: Date.parse("2026-08-28T03:30:00Z"),
          });
        },
      },
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.setInputFiles("#propertyPhotos", {
    name: "house.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("photo"),
  });
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.setInputFiles("#propertyPhotos", { name: "house.jpg", mimeType: "image/jpeg", buffer: Buffer.from("photo") });
  await expect(page.getByTestId("location-status")).toContainText("大阪府 大阪市 北区");
  await expect(page.getByLabel("都道府县")).toHaveValue("大阪府");
  await expect(page.getByLabel("市")).toHaveValue("大阪市");
  await expect(page.getByLabel("区")).toHaveValue("北区");
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("denied location keeps manual address fallback available", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_AUTH_SESSION = { provider: "supabase", username: "test-user", refreshToken: "test-refresh-token", accessToken: "test-access-token" };
  });
  await page.route("**/api/recognition", async (route) => {
    await route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "location_denied" }) });
  });
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: {
        getCurrentPosition(success, failure) {
          failure({ code: 1 });
        },
      },
    });
  });
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.setInputFiles("#propertyPhotos", {
    name: "house.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("photo"),
  });
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.setInputFiles("#propertyPhotos", { name: "house.jpg", mimeType: "image/jpeg", buffer: Buffer.from("photo") });
  await expect(page.getByTestId("location-status")).toContainText("照片位置识别失败,请手动填写");
  await expect(page.getByLabel("完整地址")).toBeEditable();
});

test("duplicate address focuses manual investigation name and can retry", async ({ page }) => {
  await page.goto("/property-analysis.html?duplicate=1");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByLabel("完整地址").fill("大阪府大阪市北区梅田");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await page.evaluate(() => {
    window.localStorage.setItem(
      "zou_house_session",
      JSON.stringify({ provider: "supabase", username: "test-user", refreshToken: "test-refresh-token", accessToken: "test-access-token" }),
    );
  });
  await page.locator("#saveProjectButton").click();
  await expect(page.getByLabel("调查记录名称")).toBeFocused();
  await expect(page.getByRole("alert")).toContainText("同一地址已有调查记录，请手工修改记录名称");
  await page.getByLabel("调查记录名称").fill("大阪府大阪市北区梅田｜二次调查");
  await page.locator("#saveProjectButton").click();
  await expect(page.getByRole("button", { name: "项目已保存" })).toBeDisabled();
});

test("existing Supabase auth session can save the preview", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await page.evaluate(() => {
    window.localStorage.setItem(
      "zou_house_session",
      JSON.stringify({ provider: "supabase", username: "test-user", refreshToken: "test-refresh-token", accessToken: "test-access-token" }),
    );
  });
  await page.locator("#saveProjectButton").click();
  await expect(page.getByRole("button", { name: "项目已保存" })).toBeDisabled();
  await expect(page.locator("#savedProjectLink")).toHaveClass(/\bhidden\b/);
  await expect(page.locator(".desktop-stepper [data-stage='save']")).toHaveAttribute("aria-current", "step");
});

test("missing intake session during save shows recovery guidance instead of a technical error", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.evaluate(() => {
    window.localStorage.setItem(
      "zou_house_session",
      JSON.stringify({ provider: "supabase", accessToken: "test-access-token" }),
    );
  });
  await page.evaluate(() => window.sessionStorage.removeItem("zou_house_property_intake_session"));
  await page.reload();

  await page.locator("#saveProjectButton").evaluate((button) => button.click());

  await expect(page.getByRole("alert")).toContainText("页面已重新加载，请重新完成前面的步骤后再保存");
  await expect(page.getByRole("alert")).not.toContainText("Cannot read properties of null");
  await expect(page.locator(".intake-progress.desktop-stepper [data-stage='purpose']")).toHaveAttribute("aria-current", "step");
  await expect(page.locator("#savedProjectLink")).toHaveClass(/\bhidden\b/);
});

test("anonymous save step keeps the temporary-project login guidance", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await expect(page.locator("#saveHeading")).toHaveText("注册后保存这个项目");
  await expect(page.locator("#saveProjectButton")).toHaveText("登录后保存项目");
  await expect(page.locator("#saveHeading").locator(".."))
    .toContainText("匿名项目会在 24 小时后到期");
});

test("existing auth session is reflected in the save step before preview", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "zou_house_session",
      JSON.stringify({
        provider: "supabase",
        username: "Gordon",
        email: "gordon@example.com",
        userId: "00000000-0000-0000-0000-000000000030",
        accessToken: "test-access-token",
        refreshToken: "test-refresh-token",
      }),
    );
  });
  await page.goto("/property-analysis.html");
  await expect(page.locator("#saveHeading")).toHaveText("保存这个项目");
  await expect(page.locator("#saveHeading")).not.toContainText("注册后保存");
  await expect(page.locator("#saveProjectButton")).toHaveText("保存这个项目");
});

test("认证会话变更事件会即时更新第 5 步保存文案", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await expect(page.locator("#saveHeading")).toHaveText("注册后保存这个项目");

  await page.evaluate(() => window.ZouAuthSession.write({
    provider: "supabase",
    username: "Gordon",
    email: "gordon@example.com",
    accessToken: "fresh-token",
    refreshToken: "refresh-token",
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
  }));
  await expect(page.locator("#saveHeading")).toHaveText("保存这个项目");
  await expect(page.locator("#saveProjectButton")).toHaveText("保存这个项目");

  await page.evaluate(() => window.ZouAuthSession.write(null));
  await expect(page.locator("#saveHeading")).toHaveText("注册后保存这个项目");
  await expect(page.locator("#saveProjectButton")).toHaveText("登录后保存项目");
});

test("过期 access token with valid refresh token stays logged in and saves without login redirect", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_SUPABASE_URL = "http://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
  });
  await page.route("**/auth/v1/token*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "renewed-access-token",
        refresh_token: "renewed-refresh-token",
        expires_in: 3600,
        user: { id: "test-user", email: "test@example.com", user_metadata: { username: "test-user" } },
      }),
    });
  });
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();

  await page.evaluate(() => {
    localStorage.setItem("sb-supabase-auth-token", JSON.stringify({
      access_token: "expired-access-token",
      refresh_token: "valid-refresh-token",
      expires_at: Math.floor(Date.now() / 1000) - 60,
      user: { id: "test-user", email: "test@example.com", user_metadata: { username: "test-user" } },
    }));
    window.dispatchEvent(new CustomEvent("zou-auth-session-changed"));
  });
  await expect.poll(() => page.evaluate(() => window.ZouAuthSession.isLoggedIn())).toBe(true);
  await expect(page.locator("#saveProjectButton")).toHaveText("保存这个项目");
  const convertRequest = page.waitForRequest((request) => request.url().endsWith("/convert") && request.method() === "POST");
  await page.locator("#saveProjectButton").click();
  const request = await convertRequest;
  expect(request.headers().authorization).toBe("Bearer renewed-access-token");
  await expect(page).toHaveURL(/property-analysis\.html/);
  await expect(page.getByRole("alert")).toContainText("项目已保存到你的账户");
});

test("明确无效 refresh token shows a clickable login recovery entry", async ({ page }) => {
  await page.addInitScript(() => {
    window.ZOUSEEKING_SUPABASE_URL = "http://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
  });
  let releaseRefresh;
  let refreshStarted;
  const refreshResponseReleased = new Promise((resolve) => {
    releaseRefresh = resolve;
  });
  const refreshRequestStarted = new Promise((resolve) => {
    refreshStarted = resolve;
  });
  await page.route("**/auth/v1/token*", async (route) => {
    refreshStarted();
    await refreshResponseReleased;
    await route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "invalid_grant" }) });
  });
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await fillLocation(page);
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await page.evaluate(() => {
    localStorage.setItem("sb-supabase-auth-token", JSON.stringify({
      access_token: "expired-access-token",
      refresh_token: "invalid-refresh-token",
      expires_at: Math.floor(Date.now() / 1000) - 60,
      user: { id: "test-user", email: "test@example.com", user_metadata: { username: "test-user" } },
    }));
    window.dispatchEvent(new CustomEvent("zou-auth-session-changed"));
  });
  // 刷新失败会清除会话；必须先挂起 token 响应，避免它在登录态断言前完成。
  const refreshPromise = page.evaluate(() => window.ZouAuthSession.ensureValidSession());
  await refreshRequestStarted;
  await expect.poll(() => page.evaluate(() => window.ZouAuthSession.read()?.refreshToken)).toBe("invalid-refresh-token");
  await expect.poll(() => page.evaluate(() => window.ZouAuthSession.isLoggedIn())).toBe(true);
  releaseRefresh();
  await refreshPromise;
  await page.locator("#saveProjectButton").click();
  await expect(page.getByRole("alert")).toContainText("登录状态已过期，请重新登录");
  await expect(page.getByRole("alert").getByRole("link", { name: "前往登录" })).toHaveAttribute("href", "profile.html?role=consumer#accountPanel");
});

test("save converts the current Tokyo apartment selections", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", username: "test-user", refreshToken: "test-refresh-token", accessToken: "test-access-token" }));
  });
  const convertRequest = page.waitForRequest((request) => request.url().endsWith("/convert") && request.method() === "POST");
  await page.goto("/property-analysis.html");
  await page.getByLabel("投资出租").check();
  await page.getByLabel("物件类型 / 房型").selectOption("apartment");
  await page.getByLabel("都道府县").selectOption("东京都");
  await page.getByLabel("市").selectOption("千代田区");
  await page.getByLabel("物件链接或说明").fill("东京都渋谷区，售价8000万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("80000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await page.locator("#saveProjectButton").click();
  const body = JSON.parse((await convertRequest).postData());
  expect(body.prefecture).toBe("东京都");
  expect(body.city).toBe("千代田区");
  expect(body.ward).toBe("__not_subdivided__");
  expect(body.asset_type).toBe("apartment");
});

test("save sends current selections when an older unversioned api-client module is cached", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", username: "test-user", refreshToken: "test-refresh-token", accessToken: "test-access-token" }));
  });
  await page.route("**/js/api-client.js**", async (route) => {
    const url = new URL(route.request().url());
    if (url.search) return route.continue();
    const response = await route.fetch();
    const source = await response.text();
    const staleSource = source.replace(
      'export function convertSession(sessionId, sessionToken, accessToken, projectName = "", query = {}) {\n  return request(`/api/intake/sessions/${encodeURIComponent(sessionId)}/convert`, {\n    method: "POST",\n    sessionToken,\n    accessToken,\n    body: { ...(projectName.trim() ? { project_name: projectName.trim() } : {}), ...query },\n  });\n}',
      'export function convertSession(sessionId, sessionToken, accessToken, projectName = "") {\n  return request(`/api/intake/sessions/${encodeURIComponent(sessionId)}/convert`, {\n    method: "POST",\n    sessionToken,\n    accessToken,\n    body: projectName.trim() ? { project_name: projectName.trim() } : {},\n  });\n}',
    );
    await route.fulfill({ response, body: staleSource });
  });

  const convertRequest = page.waitForRequest((request) => request.url().endsWith("/convert") && request.method() === "POST");
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("apartment");
  await page.getByLabel("都道府县").selectOption("东京都");
  await page.getByLabel("市").selectOption("千代田区");
  await page.getByLabel("物件链接或说明").fill("东京都渋谷区，售价8000万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("80000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await page.locator("#saveProjectButton").click();
  const body = JSON.parse((await convertRequest).postData());
  expect(body).toMatchObject({ prefecture: "东京都", city: "千代田区", ward: "__not_subdivided__", asset_type: "apartment" });
});

test("home auth tabs use switch wording distinct from the submit action", async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.locator("#showLogin")).toContainText("切换到登录");
  await expect(page.locator("#showRegister")).toContainText("切换到注册");
  await expect(page.locator("#loginForm button[type='submit']")).toHaveText("登录查询");
});

test("location validation reports the first missing required level", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await page.getByLabel("物件链接或说明").fill("有资料");

  await page.getByRole("button", { name: "开始整理资料" }).click();
  await expect(page.getByRole("alert")).toContainText("请选择都道府县");
  await fillLocation(page, { city: "大阪市", ward: "北区" });
  await page.getByLabel("都道府县").selectOption("");
  await page.getByLabel("都道府县").selectOption("大阪府");
  await page.getByLabel("市").selectOption("");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await expect(page.getByRole("alert")).toContainText("请选择市");

  await page.getByLabel("市").selectOption("大阪市");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await expect(page.getByRole("alert")).toContainText("资料已收好");
});

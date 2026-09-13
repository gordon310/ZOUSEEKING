const { test, expect } = require("@playwright/test");

const SESSION_ID = "00000000-0000-0000-0000-000000000040";

async function fillLocation(page, { prefecture = "大阪府", city = "大阪市", ward = "北区" } = {}) {
  await page.getByLabel("都道府县").selectOption(prefecture);
  await page.getByLabel("市").selectOption(city);
  await page.getByLabel("区").selectOption(ward);
}

test.beforeEach(async ({ page }) => {
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
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: SESSION_ID,
          query_key: "大阪府::大阪市::北区::塔楼::2026::8",
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
  await expect(page.getByRole("heading", { name: "免费项目预览" })).toBeVisible();
  await expect(page.locator("#previewStep").getByText("法律与交易资料")).toBeVisible();
  await expect(page.getByRole("link", { name: "查看报告" })).toHaveAttribute(
    "href",
    "report.html?key=%E5%A4%A7%E9%98%AA%E5%BA%9C%3A%3A%E5%A4%A7%E9%98%AA%E5%B8%82%3A%3A%E5%8C%97%E5%8C%BA%3A%3A%E5%A1%94%E6%A5%BC%3A%3A2026%3A%3A8",
  );
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
  await page.getByRole("button", { name: "获取照片位置并生成地址" }).click();
  await expect(page.getByTestId("location-candidate")).toHaveText("大阪府大阪市北区梅田");
  await expect(page.getByLabel("完整地址")).toHaveValue("大阪府大阪市北区梅田");
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("denied location keeps manual address fallback available", async ({ page }) => {
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
  await page.getByRole("button", { name: "获取照片位置并生成地址" }).click();
  await expect(page.getByTestId("location-status")).toContainText("无法获取设备位置");
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
      JSON.stringify({ provider: "supabase", accessToken: "test-access-token" }),
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
      JSON.stringify({ provider: "supabase", accessToken: "test-access-token" }),
    );
  });
  await page.locator("#saveProjectButton").click();
  await expect(page.getByRole("button", { name: "项目已保存" })).toBeDisabled();
  await expect(page.locator("#savedProjectLink")).toHaveAttribute("href", /report\.html\?key=/);
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

  await page.locator("#saveProjectButton").click({ force: true });

  await expect(page.getByRole("alert")).toContainText("页面已重新加载，请重新完成前面的步骤后再保存");
  await expect(page.getByRole("alert")).not.toContainText("Cannot read properties of null");
  await expect(page.locator(".desktop-stepper [data-stage='submit']")).toHaveAttribute("aria-current", "step");
  await expect(page.locator("#savedProjectLink")).toBeHidden();
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

test("save converts the current Tokyo apartment selections", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", accessToken: "test-access-token" }));
  });
  const convertRequest = page.waitForRequest((request) => request.url().endsWith("/convert") && request.method() === "POST");
  await page.goto("/property-analysis.html");
  await page.getByLabel("投资出租").check();
  await page.getByLabel("物件类型 / 房型").selectOption("apartment");
  await page.getByLabel("都道府县").selectOption("东京都");
  await page.getByLabel("市").selectOption("东京23区");
  await page.getByLabel("区").selectOption("渋谷区");
  await page.getByLabel("物件链接或说明").fill("东京都渋谷区，售价8000万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("80000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await page.locator("#saveProjectButton").click();
  const body = JSON.parse((await convertRequest).postData());
  expect(body.prefecture).toBe("东京都");
  expect(body.city).toBe("东京23区");
  expect(body.ward).toBe("渋谷区");
  expect(body.asset_type).toBe("公寓");
});

test("save sends current selections when an older unversioned api-client module is cached", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("zou_house_session", JSON.stringify({ provider: "supabase", accessToken: "test-access-token" }));
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
  await page.getByLabel("市").selectOption("东京23区");
  await page.getByLabel("区").selectOption("渋谷区");
  await page.getByLabel("物件链接或说明").fill("东京都渋谷区，售价8000万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("80000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await page.locator("#saveProjectButton").click();
  const body = JSON.parse((await convertRequest).postData());
  expect(body).toMatchObject({ prefecture: "东京都", city: "东京23区", asset_type: "公寓" });
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
  await expect(page.getByRole("alert")).toContainText("请选择区");
});

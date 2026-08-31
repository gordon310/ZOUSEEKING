const { test, expect } = require("@playwright/test");
const path = require("node:path");

const JOB_ID = "00000000-0000-0000-0000-000000000050";

test("development compatibility profile runs a legacy regional job without calling the Edge Function", async ({ page }) => {
  await page.route("**/content-library.json", async (route) => {
    await route.fulfill({
      path: path.resolve(__dirname, "../../data/content_library.json"),
      contentType: "application/json",
    });
  });
  await page.addInitScript(() => {
    window.ZOUSEEKING_RELEASE_SCOPE = {
      phase: "development",
      businessOperations: true,
      adminOperations: true,
    };
    window.ZOUSEEKING_API_BASE_URL = "http://api.test";
    window.ZOUSEEKING_SUPABASE_URL = "https://supabase.test";
    window.ZOUSEEKING_SUPABASE_ANON_KEY = "public-test-key";
    window.localStorage.setItem(
      "zou_house_session",
      JSON.stringify({
        provider: "supabase",
        userId: "00000000-0000-0000-0000-000000000030",
        email: "owner@example.com",
        username: "用户 A",
        accessToken: "test-access-token",
      }),
    );
  });

  let runCount = 0;
  let edgeCount = 0;
  let currentTaskStatus = "pending";
  page.on("request", (request) => {
    if (request.url().includes("/functions/v1/jphouse-run")) edgeCount += 1;
  });

  await page.route("https://supabase.test/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/auth/v1/user")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "00000000-0000-0000-0000-000000000030",
          email: "owner@example.com",
          user_metadata: { username: "用户 A" },
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.route("http://api.test/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/my/queries") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: JOB_ID,
            query_key: "大阪府::大阪市::北区::塔楼::2026::8",
            prefecture: "大阪府",
            city: "大阪市",
            ward: "北区",
            asset_type: "塔楼",
            year: 2026,
            month: 8,
            status: currentTaskStatus,
            generation_jobs: [
              {
                id: JOB_ID,
                status: currentTaskStatus,
                progress: currentTaskStatus === "completed" ? 100 : 5,
                current_step: currentTaskStatus === "completed" ? "完成" : "任务已创建",
                error_message: null,
                created_at: "2026-08-27T00:00:00Z",
              },
            ],
          },
        ]),
      });
      return;
    }
    if (url.pathname === `/api/jobs/${JOB_ID}/run` && request.method() === "POST") {
      runCount += 1;
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          job_id: JOB_ID,
          status: "running",
          progress: 20,
          current_step: "检查本地历史数据",
          error_message: null,
          report: null,
        }),
      });
      return;
    }
    if (url.pathname === `/api/jobs/${JOB_ID}` && request.method() === "GET") {
      currentTaskStatus = "completed";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          job_id: JOB_ID,
          status: "completed",
          progress: 100,
          current_step: "完成",
          error_message: null,
          report: {
            slug: "legacy-regional-test",
            title: "大阪府大阪市北区塔楼，租还是买？",
            publish_month: "2026年8月",
            markdown: "# 测试报告",
            xhs_content: "测试报告",
            rental: [],
            sale: [],
            summary: {},
            images: [],
            data_sources: [],
          },
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not found" }) });
  });

  await page.goto("/mypage.html");
  await expect(page.getByRole("heading", { name: "我的查询任务" })).toBeVisible();
  await page.getByRole("button", { name: "手动执行 JPHOUSE" }).click();

  await expect.poll(() => runCount).toBe(1);
  expect(edgeCount).toBe(0);
});

const { test, expect } = require("@playwright/test");

// Admin live-API wiring unit (2026-09-05).
// These tests never depend on a real backend:
//   - default page (git-tree config) must stay a working local demo with zero
//     outbound API calls;
//   - a simulated live configuration (API base + admin release scope + a
//     session token) is answered entirely by route mocks shaped like the real
//     backend/app/admin payloads, asserting the Bearer header is sent;
//   - a 403 backend must degrade to a visible permission state, never to
//     relabelled demo rows.

const MOCK_TOKEN = "test-admin-token";
const MOCK_MEMBER = {
  user_id: "11111111-1111-1111-1111-111111111111",
  username: "real-member-a",
  display_name: "真实会员甲",
  email: "真***@example.com",
  city: "",
  favorite_area: "",
  favorite_asset_type: "",
  bio: "",
  membership_tier: "pro",
  daily_query_limit: 30,
  created_at: "2026-08-01T03:00:00+00:00",
  roles: [{ role: "member_ops", granted_at: "2026-08-01T03:00:00+00:00", expires_at: null }],
  subscriptions: [],
  usage_quotas: [{ usage_kind: "query", period_key: "2026-09", limit_units: 30, consumed_units: 7, reserved_units: 0 }],
};

const MOCK_AUDIT = {
  limit: 100,
  actor_user_id: null,
  action: "",
  member_ops_scope: false,
  items: [
    {
      id: "a1",
      actor_user_id: "22222222-2222-2222-2222-222222222222",
      action: "member.pause",
      target_type: "member",
      target_id: MOCK_MEMBER.user_id,
      summary: { reason: "fraud review" },
      occurred_at: "2026-09-05T01:02:03+00:00",
    },
  ],
};

const MOCK_ORDERS = {
  total: 1,
  subtotal_amount_minor: 120000,
  page: 1,
  page_size: 20,
  items: [
    {
      id: "o1",
      order_no: "ORDER-0001",
      owner_user_id: MOCK_MEMBER.user_id,
      organization_id: null,
      product_code: "pro_monthly",
      price_version: "2026-09",
      currency: "JPY",
      amount_minor: 120000,
      status: "paid",
      provider: "stripe",
      provider_session_id: null,
      provider_payment_intent_id: "pi_1",
      paid_at: "2026-09-04T05:00:00+00:00",
      created_at: "2026-09-04T05:00:00+00:00",
      updated_at: "2026-09-04T05:00:00+00:00",
    },
  ],
};

const MOCK_REFUNDS = {
  total: 1,
  subtotal_amount_minor: 1000,
  page: 1,
  page_size: 20,
  items: [
    {
      id: "r1",
      order_id: "o1",
      order_no: "ORDER-0001",
      amount_minor: 1000,
      currency: "JPY",
      reason: "重复扣款",
      status: "succeeded",
      provider_refund_id: "re_1",
      created_at: "2026-09-05T02:00:00+00:00",
      updated_at: "2026-09-05T02:00:00+00:00",
    },
  ],
};

function collectErrors(page, { ignoreNetworkStatus = false } = {}) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${String(error)}`));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    // Browsers log a console error for any non-2xx resource response; tests
    // that deliberately stub 403/503 backends must not trip on that noise.
    if (ignoreNetworkStatus && /^Failed to load resource: the server responded with a status of (4\d\d|5\d\d)/.test(text)) return;
    errors.push(`console: ${text}`);
  });
  return errors;
}

test("default (unconfigured) admin page keeps working local demo with no API calls", async ({ page }) => {
  const errors = collectErrors(page);
  let apiCalls = 0;
  await page.route("https://zouseeking-api-staging.onrender.com/**", () => {
    apiCalls += 1;
  });

  await page.goto("/admin.html");

  const mode = await page.evaluate(() => ({
    live: window.ZouAdminMode?.live,
    disabled: window.ZouAdminMode?.realOperationsDisabled,
  }));
  expect(mode.live).toBe(false);

  // Demo member table rendered (fixture rows, never real).
  await expect(page.locator("#memberList tr[data-member-row]")).toHaveCount(4);
  await expect(page.locator("#memberCount")).toHaveText("synthetic_fixture");

  // Demo surface chrome is unchanged and honestly labelled.
  await expect(page.locator("#adminFixtureLabel")).toHaveText("演示数据，不代表生产状态");
  await expect(page.locator("#adminNotice")).not.toBeEmpty();

  // Collection/quality/service tabs carry the backend-pending badge; the new
  // audit/finance tabs exist.
  await expect(page.locator("[data-admin-tab='collection'] .admin-tab-note")).toHaveCount(1);
  await expect(page.locator("[data-admin-tab='quality'] .admin-tab-note")).toHaveCount(1);
  await expect(page.locator("[data-admin-tab='service'] .admin-tab-note")).toHaveCount(1);
  await expect(page.getByRole("tab", { name: /审计记录/ })).toHaveCount(1);
  await expect(page.getByRole("tab", { name: /财务管理/ })).toHaveCount(1);

  // Audit tab in demo shows an explicit no-fabrication empty state.
  await page.getByRole("tab", { name: /审计记录/ }).click();
  await expect(page.locator("#auditList .admin-empty")).toHaveText(/不虚构审计记录/);

  expect(apiCalls).toBe(0);
  expect(errors).toEqual([]);
});

test("reads /api/admin/* with a Bearer token when configured; 403 degrades visibly", async ({ page }) => {
    // Phase two: allow admin real operations + point the API base at a mock
    // origin (config.js only fills defaults, so pre-set values win).
    await page.addInitScript(
      ({ token }) => {
        window.ZOUSEEKING_API_BASE_URL = "https://admin-backend.test";
        window.ZOUSEEKING_RELEASE_SCOPE = Object.freeze({
          phase: "consumer_intake_preview",
          businessOperations: true,
          adminOperations: true,
        });
        window.localStorage.setItem(
          "zou_house_session",
          JSON.stringify({ provider: "supabase", accessToken: token }),
        );
      },
      { token: MOCK_TOKEN },
    );

    const errors = collectErrors(page);
    const seenAuth = [];
    const calls = [];

    await page.route("https://admin-backend.test/api/admin/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const auth = request.headers()["authorization"] || "";
      seenAuth.push(auth);
      calls.push(url.pathname);
      if (url.pathname === "/api/admin/members" && !request.url().includes("/members/")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ total: 1, page: 1, page_size: 20, items: [MOCK_MEMBER] }),
        });
        return;
      }
      if (url.pathname === "/api/admin/members/11111111-1111-1111-1111-111111111111") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...MOCK_MEMBER,
            usage_events: [
              { id: "ue1", usage_kind: "query", operation: "preview", units: 1, period_key: "2026-09", created_at: "2026-09-05T03:00:00+00:00" },
            ],
          }),
        });
        return;
      }
      if (url.pathname === "/api/admin/audit") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_AUDIT) });
        return;
      }
      if (url.pathname === "/api/admin/finance/orders") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_ORDERS) });
        return;
      }
      if (url.pathname === "/api/admin/finance/refunds") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_REFUNDS) });
        return;
      }
      await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    });

    await page.goto("/admin.html");

    const mode = await page.evaluate(() => window.ZouAdminMode?.live);
    expect(mode).toBe(true);
    await expect(page.locator("#adminFixtureLabel")).toContainText("真实后台");

    // Members tab: real rows render, write button disabled with pending label.
    await page.getByRole("tab", { name: /会员管理/ }).click();
    await expect(page.locator("#memberList tr[data-member-row]")).toHaveCount(1);
    await expect(page.locator("#memberList")).toContainText("真实会员甲");
    await expect(page.locator("#memberList")).toContainText("待后端写端点");
    await expect(page.locator("#memberList button[disabled]").first()).toBeVisible();
    await expect(page.locator("#memberCount")).toContainText("1 / 1 条");

    // Member detail view hits the detail endpoint and renders usage events.
    await page.locator("#memberList [data-member-action='view']").first().click();
    await expect(page.locator("#adminDetail")).toContainText("最近用量事件");
    await expect(page.locator("#adminDetail")).toContainText("member_ops");

    // Audit tab renders real rows.
    await page.getByRole("tab", { name: /审计记录/ }).click();
    await expect(page.locator("#auditList tr")).toHaveCount(1);
    await expect(page.locator("#auditList")).toContainText("member.pause");

    // Finance tab renders orders and refunds with totals.
    await page.getByRole("tab", { name: /财务管理/ }).click();
    await expect(page.locator("#orderList")).toContainText("ORDER-0001");
    await expect(page.locator("#orderList")).toContainText("JPY 120,000");
    await expect(page.locator("#orderTotals")).toContainText("1 笔");
    await expect(page.locator("#refundList")).toContainText("重复扣款");

    // Every request carried the session token as Bearer.
    expect(seenAuth.length).toBeGreaterThanOrEqual(4);
    seenAuth.forEach((auth) => expect(auth).toBe(`Bearer ${MOCK_TOKEN}`));
    expect(calls).toEqual(
      expect.arrayContaining([
        "/api/admin/members",
        "/api/admin/audit",
        "/api/admin/finance/orders",
        "/api/admin/finance/refunds",
      ]),
    );
    expect(errors).toEqual([]);
  });

  test("403 from the backend shows a permission state, never demo rows relabelled as real", async ({ page }) => {
    await page.addInitScript(
      ({ token }) => {
        window.ZOUSEEKING_API_BASE_URL = "https://admin-backend.test";
        window.ZOUSEEKING_RELEASE_SCOPE = Object.freeze({
          phase: "consumer_intake_preview",
          businessOperations: true,
          adminOperations: true,
        });
        window.localStorage.setItem(
          "zou_house_session",
          JSON.stringify({ provider: "supabase", accessToken: token }),
        );
      },
      { token: MOCK_TOKEN },
    );

    const errors = collectErrors(page, { ignoreNetworkStatus: true });
    await page.route("https://admin-backend.test/api/admin/**", async (route) => {
      await route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "当前账号没有后台访问权限" }) });
    });

    await page.goto("/admin.html");
    await page.getByRole("tab", { name: /会员管理/ }).click();

    // Error state is visible and explains the role gate...
    await expect(page.locator("#memberLiveStatus")).toContainText("403");
    await expect(page.locator("#memberLiveStatus")).toContainText("member_ops / super_admin");
    // ...while the live chrome still claims the backend, not demo data.
    await expect(page.locator("#adminFixtureLabel")).toContainText("真实后台");
    // No demo fixture row is offered as a fallback.
    await expect(page.locator("#memberList")).not.toContainText("MBR-001");
    await expect(page.locator("#memberList")).not.toContainText("演示会员");
    expect(errors).toEqual([]);
  });

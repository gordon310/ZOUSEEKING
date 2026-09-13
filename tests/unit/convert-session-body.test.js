const test = require("node:test");
const assert = require("node:assert/strict");

test("convertSession sends the selected location and asset type in the HTTP body", async () => {
  global.window = {
    ZOUSEEKING_API_BASE_URL: "https://api.test",
    ZouAuthSession: { getValidAccessToken: async () => "refreshed-access-token" },
  };
  let requestInit;
  global.fetch = async (_url, init) => {
    requestInit = init;
    return { ok: true, status: 200, text: async () => "{}" };
  };

  const { convertSession, getValidAccessToken } = await import(`../../web/js/api-client.js?request-body-test=${Date.now()}`);
  await convertSession("session-1", "raw-token", await getValidAccessToken(), "涩谷区干净测试2", {
    prefecture: "东京都",
    city: "东京23区",
    ward: "渋谷区",
    asset_type: "公寓",
    year: 2026,
    month: 9,
  });

  assert.equal(requestInit.headers["Content-Type"], "application/json");
  assert.equal(requestInit.headers.Authorization, "Bearer refreshed-access-token");
  assert.deepEqual(JSON.parse(requestInit.body), {
    project_name: "涩谷区干净测试2",
    prefecture: "东京都",
    city: "东京23区",
    ward: "渋谷区",
    asset_type: "公寓",
    year: 2026,
    month: 9,
  });
});

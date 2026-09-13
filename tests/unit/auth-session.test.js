const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("web/js/auth-session.js", "utf8");

function createHarness({ session, refreshResponse, refreshReject = false, initialStorageKey = "sb-example-auth-token" }) {
  const values = new Map([[initialStorageKey, JSON.stringify(session)]]);
  let refreshCalls = 0;
  const events = [];
  const fetch = async (url) => {
    refreshCalls += 1;
    if (refreshReject) {
      return { ok: false, json: async () => ({ error: "invalid_grant" }) };
    }
    return { ok: true, json: async () => refreshResponse };
  };
  const window = {
    ZOUSEEKING_SUPABASE_URL: "https://example.supabase.co",
    ZOUSEEKING_SUPABASE_ANON_KEY: "anon-key",
    localStorage: {
      getItem: (key) => values.get(key) || null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
    CustomEvent: class CustomEvent {
      constructor(type, init = {}) {
        this.type = type;
        this.detail = init.detail;
      }
    },
    dispatchEvent: (event) => events.push(event),
  };
  vm.runInNewContext(source, { window, fetch, console });
  return { auth: window.ZouAuthSession, values, events, getRefreshCalls: () => refreshCalls };
}

const expiredSession = {
  username: "member",
  email: "member@example.com",
  provider: "supabase",
  accessToken: "old-token",
  refreshToken: "refresh-token",
  expiresAt: Math.floor(Date.now() / 1000) - 3600,
};

test("expired sessions are not logged in before refresh and refresh to a usable token", async () => {
  const harness = createHarness({
    session: expiredSession,
    refreshResponse: {
      access_token: "new-token",
      refresh_token: "new-refresh-token",
      expires_in: 3600,
      user: { id: "user-1", email: "member@example.com", user_metadata: { username: "member" } },
    },
  });

  assert.equal(harness.auth.isLoggedIn(), false);
  const refreshed = await harness.auth.ensureValidSession();
  assert.equal(refreshed.accessToken, "new-token");
  assert.equal(harness.auth.isLoggedIn(), true);
  assert.equal(harness.auth.getAccessToken(), "new-token");
  const stored = JSON.parse(harness.values.get("sb-example-auth-token"));
  assert.equal(stored.access_token, "new-token");
  assert.ok(stored.expires_at > Math.floor(Date.now() / 1000) + 60);
  assert.equal(harness.getRefreshCalls(), 1);
});

test("writes a fresh auth response to the Supabase storage key and restores it", async () => {
  const harness = createHarness({ session: null, initialStorageKey: "unused" });
  const newSession = harness.auth.write({
    username: "member",
    email: "member@example.com",
    userId: "user-1",
    accessToken: "fresh-token",
    refreshToken: "fresh-refresh-token",
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
    provider: "supabase",
  });

  const stored = JSON.parse(harness.values.get("sb-example-auth-token"));
  assert.equal(stored.access_token, "fresh-token");
  assert.equal(stored.refresh_token, "fresh-refresh-token");
  assert.ok(stored.expires_at > Math.floor(Date.now() / 1000));
  assert.equal(newSession.accessToken, "fresh-token");
  assert.equal(harness.auth.isLoggedIn(), true);
  assert.equal(await harness.auth.getValidAccessToken(), "fresh-token");
});

test("derives a future expires_at from a password response and preserves expires_in", () => {
  const harness = createHarness({ session: null, initialStorageKey: "unused" });
  const before = Math.floor(Date.now() / 1000);
  const session = harness.auth.fromAuth({
    access_token: "fresh-token",
    refresh_token: "fresh-refresh-token",
    expires_in: 3600,
    user: { id: "user-1", email: "member@example.com", user_metadata: { username: "member" } },
  });
  harness.auth.write(session);
  const stored = JSON.parse(harness.values.get("sb-example-auth-token"));
  assert.equal(stored.expires_in, 3600);
  assert.ok(stored.expires_at >= before + 3599);
  assert.ok(stored.expires_at > before + 60);
  assert.notEqual(stored.expires_at, 0);
  assert.equal(harness.events.at(-1).type, "zou-auth-session-changed");
  assert.equal(harness.events.at(-1).detail.accessToken, "fresh-token");
});

test("rejects an auth response without a usable expiry instead of writing zero", () => {
  const harness = createHarness({ session: null, initialStorageKey: "unused" });
  assert.throws(
    () => harness.auth.write(harness.auth.fromAuth({ access_token: "token", user: { email: "member@example.com", user_metadata: { username: "member" } } })),
    /auth_session_expiry_missing/,
  );
  assert.equal(harness.values.has("sb-example-auth-token"), false);
});

test("cleans up a historical zero-expiry auth record during read", () => {
  const harness = createHarness({
    session: {
      access_token: "stale-token",
      refresh_token: "refresh-token",
      expires_at: 0,
      user: { email: "member@example.com", user_metadata: { username: "member" } },
    },
  });
  assert.equal(harness.auth.read(), null);
  assert.equal(harness.values.has("sb-example-auth-token"), false);
});

test("concurrent refresh requests share one in-flight refresh", async () => {
  const harness = createHarness({
    session: expiredSession,
    refreshResponse: {
      access_token: "new-token",
      refresh_token: "new-refresh-token",
      expires_in: 3600,
      user: { id: "user-1", email: "member@example.com" },
    },
  });

  const [first, second] = await Promise.all([
    harness.auth.ensureValidSession(),
    harness.auth.ensureValidSession(),
  ]);
  assert.equal(first.accessToken, "new-token");
  assert.equal(second.accessToken, "new-token");
  assert.equal(harness.getRefreshCalls(), 1);
});

test("failed refresh clears the session and exposes an actionable expiry message", async () => {
  const harness = createHarness({ session: expiredSession, refreshReject: true });

  const result = await harness.auth.ensureValidSession();
  assert.equal(result, null);
  assert.equal(harness.auth.isLoggedIn(), false);
  assert.equal(harness.values.has("sb-example-auth-token"), false);
  assert.match(harness.auth.sessionExpiredMessage("zh-Hant"), /登入狀態已過期/);
  assert.match(harness.auth.sessionExpiredMessage("en"), /session has expired/i);
  assert.match(harness.auth.sessionExpiredMessage("ja"), /ログイン状態の有効期限/);
  assert.match(harness.auth.sessionExpiredMessage("zh-CN"), /登录状态已过期/);
});

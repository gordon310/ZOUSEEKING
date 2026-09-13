(() => {
  const PROVIDERS = new Set(["supabase", "demo"]);
  const LEGACY_STORAGE_KEY = "zou_house_session";

  function storageKey() {
    const host = String(window.ZOUSEEKING_SUPABASE_URL || "").replace(/\/$/, "").replace(/^https?:\/\//, "");
    const ref = host.split(".")[0];
    return ref ? `sb-${ref}-auth-token` : "sb-zou-house-auth-token";
  }

  function normalizeExpiresAt(value) {
    const number = Number(value);
    if (Number.isFinite(number) && number > 0) {
      return Math.floor(number > 1e12 ? number / 1000 : number);
    }
    if (value) {
      const parsed = Date.parse(value);
      if (Number.isFinite(parsed)) return Math.floor(parsed / 1000);
    }
    return 0;
  }

  function fromStored(data) {
    if (!data) return null;
    if (data.provider === "demo") return data;
    return fromAuth(data);
  }

  function read() {
    try {
      const value = window.localStorage.getItem(storageKey()) || window.localStorage.getItem(LEGACY_STORAGE_KEY);
      return value ? fromStored(JSON.parse(value)) : null;
    } catch {
      return null;
    }
  }

  function write(session) {
    try {
      if (session?.provider === "supabase") {
        window.localStorage.setItem(storageKey(), JSON.stringify({
          access_token: session.accessToken || "",
          refresh_token: session.refreshToken || "",
          expires_in: Math.max(0, expiresAt(session) - Math.floor(Date.now() / 1000)),
          expires_at: expiresAt(session),
          token_type: "bearer",
          user: session.user || {
            id: session.userId || "",
            email: session.email || "",
            user_metadata: { username: session.username || "" },
          },
        }));
      } else if (session) {
        window.localStorage.setItem(storageKey(), JSON.stringify(session));
      } else {
        window.localStorage.removeItem(storageKey());
      }
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    } catch {
      // A blocked storage area must degrade to logged out without breaking the page.
    }
    try {
      window.dispatchEvent?.(new window.CustomEvent("zou-auth-session-changed", { detail: session }));
    } catch {
      // Event dispatch is optional in minimal test and embedded contexts.
    }
    return session;
  }

  function expiresAt(session) {
    const value = session?.expiresAt ?? session?.expires_at;
    return normalizeExpiresAt(value);
  }

  function isLoggedIn(session = read()) {
    if (!session?.username || !PROVIDERS.has(session?.provider)) return false;
    if (session.provider === "demo") return true;
    return Boolean(session.accessToken && expiresAt(session) > Math.floor(Date.now() / 1000) + 60);
  }

  function authConfig() {
    return {
      url: String(window.ZOUSEEKING_SUPABASE_URL || "").replace(/\/$/, ""),
      anonKey: window.ZOUSEEKING_SUPABASE_ANON_KEY || "",
    };
  }

  async function request(path, options, anonKey, token) {
    const response = await fetch(`${options.url}/auth/v1${path}`, {
      ...options,
      headers: {
        apikey: anonKey,
        Authorization: `Bearer ${token || anonKey}`,
        "Content-Type": "application/json",
      },
    });
    if (!response.ok) throw new Error("auth_session_invalid");
    return response.json();
  }

  function fromAuth(data, fallback = {}) {
    const user = data?.user || {};
    const metadata = user.user_metadata || {};
    const email = user.email || fallback.email || "";
    return {
      username: metadata.username || fallback.username || email.split("@")[0] || "小象用户",
      email,
      userId: user.id || fallback.userId || "",
      accessToken: data?.access_token || data?.accessToken || fallback.accessToken || "",
      refreshToken: data?.refresh_token || data?.refreshToken || fallback.refreshToken || "",
      expiresAt: normalizeExpiresAt(data?.expires_at || data?.expiresAt) || (data?.expires_in ? Math.floor(Date.now() / 1000) + Number(data.expires_in) : normalizeExpiresAt(fallback.expiresAt || fallback.expires_at)),
      user,
      provider: data?.provider || fallback.provider || "supabase",
    };
  }

  let refreshInFlight = null;

  async function refresh(session) {
    if (refreshInFlight) return refreshInFlight;
    const { url, anonKey } = authConfig();
    if (!url || !anonKey || !session?.refreshToken) return null;
    refreshInFlight = (async () => {
      try {
        const data = await request("/token?grant_type=refresh_token", {
          url,
          method: "POST",
          body: JSON.stringify({ refresh_token: session.refreshToken }),
        }, anonKey);
        return write(fromAuth(data, session));
      } catch {
        write(null);
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();
    return refreshInFlight;
  }

  async function ensureValidSession(session = read()) {
    if (!session || !PROVIDERS.has(session.provider)) {
      if (session) write(null);
      return null;
    }
    if (isLoggedIn(session)) return session;
    if (session.provider !== "supabase") {
      write(null);
      return null;
    }
    return refresh(session);
  }

  async function restore() {
    const session = read();
    if (!session || !PROVIDERS.has(session.provider)) {
      if (session) write(null);
      return null;
    }
    if (session.provider !== "supabase") return session;
    if (!isLoggedIn(session)) return ensureValidSession(session);
    const { url, anonKey } = authConfig();
    if (!url || !anonKey || !session.accessToken) {
      if (!session.accessToken) write(null);
      return session.accessToken ? session : null;
    }
    try {
      const user = await request("/user", { url }, anonKey, session.accessToken);
      return write(fromAuth({ user }, session));
    } catch {
      return ensureValidSession(session);
    }
  }

  function sessionExpiredMessage(locale = "zh-CN") {
    return {
      "zh-Hant": "登入狀態已過期，請重新登入。",
      en: "Your session has expired. Please log in again.",
      ja: "ログイン状態の有効期限が切れました。もう一度ログインしてください。",
      "zh-CN": "登录状态已过期，请重新登录。",
    }[locale] || "登录状态已过期，请重新登录。";
  }

  window.ZouAuthSession = Object.freeze({
    read,
    write,
    isLoggedIn,
    restore,
    ensureValidSession,
    sessionExpiredMessage,
    getAccessToken: () => {
      const session = read();
      return isLoggedIn(session) && session.provider === "supabase" ? session.accessToken || "" : "";
    },
    getValidAccessToken: async () => (await ensureValidSession())?.accessToken || "",
    storageKey,
  });
})();

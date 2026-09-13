(() => {
  const STORAGE_KEY = "zou_house_session";
  const PROVIDERS = new Set(["supabase", "demo"]);

  function read() {
    try {
      const value = window.localStorage.getItem(STORAGE_KEY);
      return value ? JSON.parse(value) : null;
    } catch {
      return null;
    }
  }

  function write(session) {
    try {
      if (session) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // A blocked storage area must degrade to logged out without breaking the page.
    }
    return session;
  }

  function expiresAt(session) {
    const value = session?.expiresAt ?? session?.expires_at;
    if (typeof value === "number") return value;
    if (value) {
      const parsed = Date.parse(value);
      if (Number.isFinite(parsed)) return Math.floor(parsed / 1000);
    }
    return 0;
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
      accessToken: data?.access_token || fallback.accessToken || "",
      refreshToken: data?.refresh_token || fallback.refreshToken || "",
      expiresAt: data?.expires_at || (data?.expires_in ? Math.floor(Date.now() / 1000) + Number(data.expires_in) : fallback.expiresAt || fallback.expires_at || 0),
      provider: "supabase",
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
  });
})();

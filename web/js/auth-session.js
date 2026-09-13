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

  function isLoggedIn(session = read()) {
    return Boolean(session?.username && PROVIDERS.has(session?.provider));
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
      provider: "supabase",
    };
  }

  async function restore() {
    const session = read();
    if (!session || !isLoggedIn(session)) {
      if (session) write(null);
      return null;
    }
    if (session.provider !== "supabase") return session;
    const { url, anonKey } = authConfig();
    if (!url || !anonKey || !session.accessToken) {
      if (!session.accessToken) write(null);
      return session.accessToken ? session : null;
    }
    try {
      const user = await request("/user", { url }, anonKey, session.accessToken);
      return write(fromAuth({ user }, session));
    } catch {
      if (!session.refreshToken) {
        write(null);
        return null;
      }
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
      }
    }
  }

  window.ZouAuthSession = Object.freeze({
    read,
    write,
    isLoggedIn,
    restore,
    getAccessToken: () => {
      const session = read();
      return isLoggedIn(session) && session.provider === "supabase" ? session.accessToken || "" : "";
    },
  });
})();

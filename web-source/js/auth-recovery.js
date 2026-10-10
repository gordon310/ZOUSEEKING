(function exposeAuthRecovery(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ZouAuthRecovery = api;
})(typeof window !== "undefined" ? window : globalThis, () => {
  const PASSWORD_MIN_LENGTH = 6;
  const PASSWORD_MAX_LENGTH = 128;

  function isPasswordValid(password) {
    return (
      typeof password === "string" &&
      password.length >= PASSWORD_MIN_LENGTH &&
      password.length <= PASSWORD_MAX_LENGTH &&
      !/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/.test(password)
    );
  }

  function buildAuthReturnUrl(href) {
    try {
      const current = new URL(href);
      const destination = current.searchParams.get("return_to") || current.searchParams.get("return");
      if (!destination || /[\\\s]/.test(destination)) return "";
      const target = new URL(destination, current);
      const directory = current.pathname.slice(0, current.pathname.lastIndexOf("/") + 1);
      const pages = ["property-analysis.html", "projects.html", "project.html", "report.html", "data-query.html", "analysis.html", "mypage.html"];
      if (target.origin !== current.origin || target.username || target.password || !pages.some((page) => target.pathname === directory + page)) return "";
      return target.href;
    } catch {
      return "";
    }
  }

  function buildResetRedirectUrl(origin, path = "reset-password.html") {
    const base = String(origin || "").replace(/\/$/, "");
    return new URL(path, `${base}/`).toString();
  }

  function resetRequestResultMessage() {
    return "如果该邮箱已注册，重置邮件会发送到邮箱；请查收收件箱和垃圾邮件。";
  }

  function resetRequestErrorMessage() {
    return "暂时无法发送重置邮件，请稍后再试。";
  }

  function passwordUpdateErrorMessage() {
    return "密码更新未完成，请重新打开有效链接后再试。";
  }

  function classifyRecoverySession(session) {
    return session?.accessToken && session?.user?.id ? "valid" : "invalid";
  }

  function buildAuthHeaders(anonKey, accessToken = anonKey) {
    return {
      apikey: anonKey,
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    };
  }

  function createAuthApi({ supabaseUrl, anonKey, fetchImpl = fetch }) {
    const base = String(supabaseUrl || "").replace(/\/$/, "");
    async function request(path, options = {}, accessToken = anonKey) {
      const response = await fetchImpl(`${base}/auth/v1${path}`, {
        ...options,
        headers: { ...buildAuthHeaders(anonKey, accessToken), ...(options.headers || {}) },
      });
      const text = await response.text();
      let payload = null;
      try { payload = text ? JSON.parse(text) : null; } catch { payload = text; }
      if (!response.ok) throw new Error(payload?.message || payload?.msg || "auth request failed");
      return payload;
    }
    return {
      resetPasswordForEmail(email, { redirectTo }) {
        return request(`/recover?redirect_to=${encodeURIComponent(redirectTo)}`, {
          method: "POST",
          body: JSON.stringify({ email }),
        });
      },
      updateUser({ password }, accessToken) {
        return request("/user", { method: "PUT", body: JSON.stringify({ password }) }, accessToken);
      },
      getUser(accessToken) {
        return request("/user", {}, accessToken);
      },
      async establishRecoverySession(location) {
        const hash = String(location?.hash || "");
        const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
        if (params.get("type") !== "recovery" || !params.get("access_token")) return null;
        const accessToken = params.get("access_token");
        const refreshToken = params.get("refresh_token") || "";
        const user = await this.getUser(accessToken);
        return { accessToken, refreshToken, user };
      },
    };
  }

  return {
    isPasswordValid,
    buildAuthReturnUrl,
    buildResetRedirectUrl,
    resetRequestResultMessage,
    resetRequestErrorMessage,
    passwordUpdateErrorMessage,
    classifyRecoverySession,
    createAuthApi,
  };
});

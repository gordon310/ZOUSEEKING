(() => {
  // Read-only API client for the back-office admin boundary
  // (backend/app/admin/routes.py). No DOM work here: this module only maps the
  // documented GET endpoints to fetch() calls carrying the Supabase access
  // token as a Bearer header.
  //
  // The access-token lookup mirrors api-client.js getExistingAccessToken().
  // api-client.js is an ES module used by the intake/project pages; this page
  // loads classic scripts, so the ~20-line read-only lookup is duplicated here
  // rather than forcing a module loader into admin.html.

  function getAccessToken() {
    const directSession = window.ZOUSEEKING_AUTH_SESSION || window.__ZOUSEEKING_AUTH_SESSION__;
    if (directSession && typeof directSession.accessToken === "string") return directSession.accessToken;
    try {
      const sessionStorageValue = window.sessionStorage.getItem("zou_house_auth_session");
      const sessionStorageSession = sessionStorageValue ? JSON.parse(sessionStorageValue) : null;
      if (sessionStorageSession?.accessToken) return sessionStorageSession.accessToken;
    } catch {
      // A blocked storage area should not break the page.
    }
    try {
      const legacyValue = window.localStorage.getItem("zou_house_session");
      const legacySession = legacyValue ? JSON.parse(legacyValue) : null;
      return legacySession?.provider === "supabase" ? legacySession.accessToken || "" : "";
    } catch {
      return "";
    }
  }

  class AdminApiError extends Error {
    constructor(message, status = 0, payload = null, code = "") {
      super(message);
      this.name = "AdminApiError";
      this.status = status;
      this.payload = payload;
      this.code = code || (payload && typeof payload === "object" ? payload.code || "" : "");
    }
  }

  function buildQuery(params = {}) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      search.set(key, String(value));
    });
    const query = search.toString();
    return query ? `?${query}` : "";
  }

  async function request(path, options = {}) {
    const { method = "GET", body = null, params = {} } = options;
    const token = getAccessToken();
    if (!token) {
      throw new AdminApiError("未检测到有效登录会话，无法访问后台。", 401, null, "no_session");
    }
    const url = `${window.ZouAdminMode.apiBaseUrl}${path}${buildQuery(params)}`;
    const headers = { Accept: "application/json" };
    if (body !== null && body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await fetch(url, {
        method,
        headers: {
          ...headers,
          Authorization: `Bearer ${token}`,
        },
        body: body !== null && body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (error) {
      throw new AdminApiError("无法连接后台服务，请检查网络后重试。", 0, null, "network");
    }
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
    if (!response.ok) {
      const detail = payload && typeof payload === "object" ? payload.detail || payload.message : payload;
      const message = detail && typeof detail === "object" ? detail.message : detail;
      throw new AdminApiError(message || `后台请求失败（HTTP ${response.status}）。`, response.status, payload);
    }
    return payload;
  }

  window.ZouAdminApi = Object.freeze({
    // GET /api/admin/members?q=&page=&page_size=
    listMembers({ q = "", page = 1, page_size = 20 } = {}) {
      return request("/api/admin/members", { params: { q, page, page_size } });
    },
    // GET /api/admin/members/{user_id}
    getMember(userId) {
      return request(`/api/admin/members/${encodeURIComponent(userId)}`);
    },
    // POST /api/admin/members/{user_id}/status { status: 'active'|'suspended' }
    // -> { user_id, status, previous_status, changed } (idempotent 200)
    setMemberStatus(userId, status) {
      return request(
        `/api/admin/members/${encodeURIComponent(userId)}/status`,
        { method: "POST", body: { status } },
      );
    },
    // GET /api/admin/audit?actor=&action=&since=&limit=
    listAudit({ actor = "", action = "", since = "", limit = 100 } = {}) {
      return request("/api/admin/audit", { params: { actor, action, since, limit } });
    },
    // GET /api/admin/finance/orders?status=&page=
    listOrders({ status = "", page = 1, page_size = 20 } = {}) {
      return request("/api/admin/finance/orders", { params: { status, page, page_size } });
    },
    // GET /api/admin/finance/refunds?status=&page=
    listRefunds({ status = "", page = 1, page_size = 20 } = {}) {
      return request("/api/admin/finance/refunds", { params: { status, page, page_size } });
    },
    // GET /api/admin/collection/runs?status=&source_key=&page=&page_size=
    // -> { total, page, page_size, items: [...] }
    listCollectionRuns({ status = "", source_key = "", page = 1, page_size = 20 } = {}) {
      return request("/api/admin/collection/runs", {
        params: { status, source_key, page, page_size },
      });
    },
    // POST /api/admin/collection/runs { source_key, source_type } -> queued run
    enqueueCollectionRun({ source_key, source_type } = {}) {
      return request("/api/admin/collection/runs", {
        method: "POST",
        body: { source_key, source_type },
      });
    },
    // GET /api/admin/internal/me  -> { user_id, roles: [...] }
    getMe() {
      return request("/api/admin/internal/me");
    },
    // GET /api/admin/internal/roles -> { items: [...] }
    listRoles() {
      return request("/api/admin/internal/roles");
    },
    // POST /api/admin/internal/roles { user_id, role, note?, expires_at? }
    grantRole({ user_id, role, note = "", expires_at = "" } = {}) {
      return request("/api/admin/internal/roles", {
        method: "POST",
        body: { user_id, role, note: note || undefined, expires_at: expires_at || undefined },
      });
    },
    // DELETE /api/admin/internal/roles/{user_id}/{role}
    revokeRole(userId, role) {
      return request(
        `/api/admin/internal/roles/${encodeURIComponent(userId)}/${encodeURIComponent(role)}`,
        { method: "DELETE" },
      );
    },
    getAccessToken,
    AdminApiError,
  });
})();

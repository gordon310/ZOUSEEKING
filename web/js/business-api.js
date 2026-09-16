(() => {
  const base = (window.ZOUSEEKING_API_BASE_URL || window.localStorage.getItem("zou_house_api_base") || "").replace(/\/$/, "");

  function accessToken() {
    return window.ZouAuthSession?.getAccessToken?.() || "";
  }

  async function request(path, options = {}) {
    if (!base) throw new Error("API base URL is not configured");
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    const token = await window.ZouAuthSession?.getValidAccessToken?.() || accessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${base}${path}`, { ...options, headers });
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = text; }
    if (!response.ok) {
      const detail = payload && typeof payload === "object" ? payload.error?.message || payload.detail?.message || payload.detail || payload.message : payload;
      const error = new Error(typeof detail === "string" ? detail : `API ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  window.ZouBusinessApi = {
    hasToken: () => Boolean(accessToken()),
    getBillingPrices: () => request("/api/billing/prices"),
    getBillingStatus: () => request("/api/billing/status"),
    getSubscription: () => request("/api/billing/subscription"),
    getMe: () => request("/api/me"),
    getUsageSummary: () => request("/api/usage/summary"),
    getOrganization: () => request("/api/org/me"),
    listOrganizationMembers: () => request("/api/org/members"),
    listExports: () => request("/api/exports"),
    createExport: () => request("/api/exports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }),
    downloadExport: async (exportId) => {
      const headers = {};
      const token = await window.ZouAuthSession?.getValidAccessToken?.() || accessToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const response = await fetch(`${base}/api/exports/${encodeURIComponent(exportId)}`, { headers });
      if (!response.ok) throw new Error(`API ${response.status}`);
      return response.blob();
    },
    createBillingCheckout: (productCode, billingRegion = "CN") => request("/api/billing/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_code: productCode, billing_region: billingRegion }),
    }),
    createBillingPortal: () => request("/api/billing/portal", { method: "POST" }),
  };
})();

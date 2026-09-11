(() => {
  const base = (window.ZOUSEEKING_API_BASE_URL || window.localStorage.getItem("zou_house_api_base") || "").replace(/\/$/, "");

  function accessToken() {
    try {
      const raw = window.localStorage.getItem("zou_house_session");
      const session = raw ? JSON.parse(raw) : null;
      return session?.provider === "supabase" ? session.accessToken || "" : "";
    } catch {
      return "";
    }
  }

  async function request(path, options = {}) {
    if (!base) throw new Error("API base URL is not configured");
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    const token = accessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${base}${path}`, { ...options, headers });
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = text; }
    if (!response.ok) {
      const detail = payload && typeof payload === "object" ? payload.detail || payload.message : payload;
      throw new Error(typeof detail === "string" ? detail : `API ${response.status}`);
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
    createBillingCheckout: (productCode, billingRegion = "CN") => request("/api/billing/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_code: productCode, billing_region: billingRegion }),
    }),
    createBillingPortal: () => request("/api/billing/portal", { method: "POST" }),
  };
})();

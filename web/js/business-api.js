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
    getOrganizationUsage: () => request("/api/org/usage"),
    getOrganizationBilling: () => request("/api/org/billing"),
    listOrganizationMembers: () => request("/api/org/members"),
    createOrganizationInvitation: (email, role) => request("/api/org/invitations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, role }) }),
    listOrganizationInvitations: () => request("/api/org/invitations"),
    revokeOrganizationInvitation: (id) => request(`/api/org/invitations/${encodeURIComponent(id)}/revoke`, { method: "POST" }),
    acceptOrganizationInvitation: (token) => request("/api/org/invitations/accept", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) }),
    listServiceTasks: () => request("/api/org/service-tasks"),
    listCreatorServiceTasks: () => request("/api/service/tasks"),
    grantCreatorServiceTaskConsent: (id) => request(`/api/service/tasks/${encodeURIComponent(id)}/consent`, { method: "POST" }),
    confirmCreatorServiceTask: (id) => request(`/api/service/tasks/${encodeURIComponent(id)}/confirm-completion`, { method: "POST" }),
    applyServiceTask: (id, assignedMemberUserId) => request(`/api/org/service-tasks/${encodeURIComponent(id)}/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ assigned_member_user_id: assignedMemberUserId }) }),
    withdrawServiceTask: (id) => request(`/api/org/service-tasks/${encodeURIComponent(id)}/withdraw`, { method: "POST" }),
    grantServiceTaskConsent: (id) => request(`/api/org/service-tasks/${encodeURIComponent(id)}/consent`, { method: "POST" }),
    completeServiceTask: (id) => request(`/api/org/service-tasks/${encodeURIComponent(id)}/complete`, { method: "POST" }),
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
    listOrganizationExports: () => request("/api/org/exports"),
    createOrganizationExport: () => request("/api/org/exports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }),
    downloadOrganizationExport: async (exportId) => {
      const headers = {};
      const token = await window.ZouAuthSession?.getValidAccessToken?.() || accessToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const response = await fetch(`${base}/api/org/exports/${encodeURIComponent(exportId)}`, { headers });
      if (!response.ok) { const error = new Error(`API ${response.status}`); error.status = response.status; throw error; }
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

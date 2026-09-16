(() => {
  const page = document.body?.dataset.businessPage;
  const i18n = window.ZouI18n;
  if (!page || !i18n) return;

  const t = (key, fallback = "") => i18n.t(key, fallback);

  function format(key, values = {}, fallback = "") {
    return Object.entries(values).reduce(
      (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
      t(key, fallback),
    );
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setNotice(id, text) {
    const element = byId(id);
    if (element) element.textContent = text;
  }

  function renderSideSummary() {
    const text = t("business.liveDataOnly");
    ["businessSeatSummary", "organizationSeatSummary"].forEach((id) => {
      const element = byId(id);
      if (element) element.textContent = text;
    });
  }

  function status(textKey, className = "") {
    return `<span class="business-status ${className}">${escapeHtml(t(textKey))}</span>`;
  }

  function currencyLabel(value) {
    return { CNY: "CNY", JPY: "JPY", USD: "USD" }[value] || "CNY";
  }

  function orgStatus(value) {
    return { paid: "business.paid", active: "business.active" }[value] ? t({ paid: "business.paid", active: "business.active" }[value]) : t("business.notAvailable");
  }

  function renderOrganization() {
    const list = byId("organizationMembers");
    if (!list) return;
    list.innerHTML = `<tr><td colspan="4">${escapeHtml(t("business.organizationLoading"))}</td></tr>`;
    const roleLabels = { owner: "business.owner", admin: "business.adminRole", member: "business.memberRole" };
    const statusLabels = { active: "business.active", inactive: "business.inactive" };
    const renderMembers = (members) => {
      if (!members.length) {
        list.innerHTML = `<tr><td colspan="4">${escapeHtml(t("business.organizationEmpty"))}</td></tr>`;
        return;
      }
      list.innerHTML = members.map((member) => `
        <tr data-member-row>
          <th scope="row">${escapeHtml(member.display_name || t("business.memberFallback"))}</th>
          <td data-label="${escapeHtml(t("business.role"))}">${escapeHtml(t(roleLabels[member.role] || "business.memberRole"))}</td>
          <td data-label="${escapeHtml(t("business.status"))}">${escapeHtml(t(statusLabels[member.status] || "business.inactive"))}</td>
          <td data-label="${escapeHtml(t("business.joinedAt"))}">${escapeHtml(member.joined_at || t("business.dateUnavailable"))}</td>
        </tr>
      `).join("");
    };
    const load = async () => {
      if (!window.ZouBusinessApi) throw new Error("api_unavailable");
      const me = await window.ZouBusinessApi.getOrganization();
      let members = { members: [] };
      try { members = await window.ZouBusinessApi.listOrganizationMembers(); } catch { /* summary remains usable */ }
      if (!me?.organization) {
        byId("organizationAccountHeading").textContent = t("business.organizationNone");
        byId("organizationPlanName").textContent = "";
        byId("organizationName").textContent = t("business.organizationNone");
        byId("organizationRole").textContent = "—";
        byId("businessSeatSummary").textContent = "—";
        byId("organizationSeatSummary").textContent = "—";
        setNotice("organizationNotice", t("business.organizationEmpty"));
        renderMembers([]);
        return;
      }
      const seatText = format("business.seatSummary", { used: me.seats?.used ?? 0, total: me.seats?.limit ?? 0 });
      byId("organizationAccountHeading").textContent = me.organization.name || t("business.organizationNone");
      byId("organizationPlanName").textContent = me.plan?.name || t("business.notAvailable");
      byId("organizationName").textContent = me.organization.name || t("business.organizationNone");
      byId("organizationRole").textContent = t(roleLabels[me.role] || "business.memberRole");
      byId("businessSeatSummary").textContent = seatText;
      byId("organizationSeatSummary").textContent = seatText;
      setNotice("organizationNotice", t("business.organizationLive"));
      renderMembers(Array.isArray(members?.members) ? members.members : []);
      const manager = ["owner", "admin"].includes(me.role);
      const inviteButton = byId("inviteMemberButton");
      const form = byId("organizationInviteForm");
      if (inviteButton) inviteButton.hidden = !manager;
      if (form) form.hidden = !manager;
      const invitationPanel = byId("organizationInvitations");
      if (manager && invitationPanel && window.ZouBusinessApi.listOrganizationInvitations) {
        const invitations = await window.ZouBusinessApi.listOrganizationInvitations();
        invitationPanel.replaceChildren(...(invitations?.invitations || []).map((item) => {
          const row = document.createElement("p");
          row.textContent = `${item.email} · ${t(`business.invitationStatus.${item.status}`, item.status)}`;
          if (item.status === "pending") {
            const revoke = document.createElement("button"); revoke.type = "button"; revoke.className = "business-button secondary"; revoke.textContent = t("business.revokeInvite");
            revoke.addEventListener("click", async () => { await window.ZouBusinessApi.revokeOrganizationInvitation(item.id); await load(); }); row.append(" ", revoke);
          }
          return row;
        }));
      }
    };
    byId("organizationInviteForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget; const button = form.querySelector("button[type=submit]"); button.disabled = true;
      try {
        const result = await window.ZouBusinessApi.createOrganizationInvitation(form.email.value, form.role.value);
        const link = `${window.location.origin}${window.location.pathname.replace(/organization\.html$/, "invite.html")}?token=${encodeURIComponent(result.invite_token)}`;
        const output = byId("inviteResult"); output.textContent = t("business.inviteShownOnce");
        const copy = document.createElement("button"); copy.type = "button"; copy.className = "business-button secondary"; copy.textContent = t("business.copyInvite"); copy.addEventListener("click", () => navigator.clipboard.writeText(link));
        output.append(" ", copy); form.reset();
      } catch (error) { setNotice("inviteResult", error?.status === 409 ? t("business.inviteFullOrDuplicate") : t("business.inviteError")); }
      finally { button.disabled = false; }
    });
    load().catch((error) => {
      const forbidden = error?.status === 401 || error?.status === 403;
      const message = forbidden ? t("business.organizationForbidden") : t("business.organizationUnavailable");
      setNotice("organizationNotice", message);
      list.innerHTML = `<tr><td colspan="4">${escapeHtml(message)}</td></tr>`;
    });
  }

  function renderInvite() {
    const notice = byId("invitePageNotice"); const button = byId("acceptInviteButton"); const token = new URLSearchParams(window.location.search).get("token") || "";
    if (!token) { notice.textContent = t("business.inviteInvalid"); return; }
    if (!window.ZouAuthSession?.isLoggedIn?.()) return;
    byId("inviteLoginLink").hidden = true; button.hidden = false;
    button.addEventListener("click", async () => { try { await window.ZouBusinessApi.acceptOrganizationInvitation(token); window.location.assign("organization.html"); } catch (error) { const key = error?.status === 403 ? "business.inviteMismatch" : error?.status === 409 ? "business.inviteFull" : error?.status === 410 ? "business.inviteExpiredOrRevoked" : "business.inviteInvalid"; notice.textContent = t(key); } });
  }

  function renderBilling() {
    const plans = byId("billingPlans");
    const status = byId("billingCurrentPlan");
    const price = byId("billingPrice");
    const portal = byId("autoRenewButton");
    if (!plans) return;
    plans.textContent = t("business.billingCopy");
    status.textContent = t("business.notAvailable");
    price.textContent = "";
    portal.textContent = t("business.openPortal");
    portal.disabled = true;
    setNotice("billingNotice", t("business.billingUnavailable"));
    if (!window.ZouBusinessApi) return;
    Promise.allSettled([window.ZouBusinessApi.getBillingPrices(), window.ZouBusinessApi.getMe(), window.ZouBusinessApi.getSubscription(), window.ZouBusinessApi.getOrganization(), window.ZouBusinessApi.getOrganizationBilling()]).then(([pricesResult, meResult, subscriptionResult, orgResult, orgBillingResult]) => {
      const organization = orgResult.status === "fulfilled" ? orgResult.value?.organization : null;
      const orgBilling = orgBillingResult.status === "fulfilled" ? orgBillingResult.value : null;
      if (organization && orgBilling) {
        status.textContent = organization.name || t("business.organizationNone");
        price.textContent = orgBilling.subscription ? `${escapeHtml(orgBilling.subscription.product_code)} · ${escapeHtml(orgStatus(orgBilling.subscription.status))}` : t("business.notSubscribed");
        portal.disabled = true;
        if (Array.isArray(orgBilling.orders) && orgBilling.orders.length) {
          plans.innerHTML = orgBilling.orders.map((item) => `<article class="business-card"><h3>${escapeHtml(item.period || "—")}</h3><p>${escapeHtml(item.currency || "")} ${escapeHtml(String(item.amount_minor ?? 0))} · ${escapeHtml(orgStatus(item.status))}</p></article>`).join("");
        } else {
          plans.innerHTML = `<p class="business-panel-copy">${escapeHtml(t("business.noInvoiceData"))}</p>`;
        }
        setNotice("billingNotice", t("business.billingLive"));
        return;
      }
      if (organization && orgBillingResult.status === "rejected" && orgBillingResult.reason?.status === 403) {
        status.textContent = organization.name || t("business.organizationNone");
        price.textContent = "";
        portal.disabled = true;
        plans.innerHTML = `<p class="business-panel-copy">${escapeHtml(t("business.organizationForbidden"))}</p>`;
        setNotice("billingNotice", t("business.organizationForbidden"));
        return;
      }
      const me = meResult.status === "fulfilled" ? meResult.value : null;
      const subscription = subscriptionResult.status === "fulfilled" ? subscriptionResult.value : null;
      if (me) status.textContent = me.membership_tier || t("business.notAvailable");
      if (subscription) {
        price.textContent = `${escapeHtml(t(`business.subscriptionStatus.${subscription.status}`, subscription.status))}${subscription.current_period_end ? ` · ${escapeHtml(subscription.current_period_end)}` : ""}`;
        portal.disabled = false;
        portal.onclick = async () => {
          try {
            const result = await window.ZouBusinessApi.createBillingPortal();
            if (result?.url) window.location.assign(result.url);
          } catch { setNotice("billingNotice", t("business.billingUnavailable")); }
        };
      }
      if (pricesResult.status === "fulfilled" && Array.isArray(pricesResult.value) && pricesResult.value.length) {
        plans.innerHTML = pricesResult.value.map((item) => `<article class="business-card"><h3>${escapeHtml(item.product_code || "")}</h3><p>${escapeHtml(item.currency || "")} ${escapeHtml(item.amount_minor == null ? "" : String(item.amount_minor))}</p>${item.mode === "subscription" && !subscription ? `<button class="business-button" type="button" data-checkout-product="${escapeHtml(item.product_code)}">${escapeHtml(t("business.upgrade"))}</button>` : ""}</article>`).join("");
        plans.querySelectorAll("[data-checkout-product]").forEach((button) => button.addEventListener("click", async () => {
          try {
            const result = await window.ZouBusinessApi.createBillingCheckout(button.dataset.checkoutProduct);
            if (result?.url) window.location.assign(result.url);
          } catch { setNotice("billingNotice", t("business.billingUnavailable")); }
        }));
        setNotice("billingNotice", t("business.billingLive"));
      }
    });
  }

  function renderUsage() {
    const cards = byId("usageCards");
    const list = byId("usageList");
    if (!cards || !list) return;
    cards.textContent = t("business.loading");
    list.textContent = t("business.usageEventsUnavailable");
    setNotice("usageNotice", t("business.usageUnavailable"));
    if (!window.ZouBusinessApi) return;
    Promise.allSettled([window.ZouBusinessApi.getOrganization(), window.ZouBusinessApi.getOrganizationUsage(), window.ZouBusinessApi.getUsageSummary()]).then(([orgResult, orgUsageResult, personalResult]) => {
      const org = orgResult.status === "fulfilled" ? orgResult.value : null;
      let value = orgUsageResult.status === "fulfilled" ? orgUsageResult.value : null;
      if (org?.organization && value?.organization) {
        const usageCopy = byId("usageCopy");
        if (usageCopy) usageCopy.textContent = t("business.organizationUsageCopy");
        const labels = { queries: "business.usageQuery", reports: "business.usageReports", exports_rows: "business.usageExport", analysis: "business.usageAnalysis" };
        cards.innerHTML = Object.entries(value.entitlements || {}).map(([key, item]) => `<article class="business-card"><h3>${escapeHtml(t(labels[key] || "business.notAvailable"))}</h3><p>${escapeHtml(String(item.used ?? 0))} / ${escapeHtml(String(item.limit ?? t("business.unknownLimit")))}</p></article>`).join("") || `<p>${escapeHtml(t("business.organizationEmpty"))}</p>`;
        const periodElement = byId("usagePeriod");
        if (periodElement) periodElement.textContent = `${t("business.period")}: ${escapeHtml(value.period || "—")}`;
        setNotice("usageNotice", t("business.usageLive"));
        list.textContent = t("business.usageEventsUnavailable");
        return;
      }
      if (org?.organization && orgUsageResult.status === "rejected") {
        cards.textContent = t("business.usageUnavailable");
        setNotice("usageNotice", orgUsageResult.reason?.status === 403 ? t("business.organizationForbidden") : t("business.usageUnavailable"));
        return;
      }
      if (personalResult.status === "rejected") throw personalResult.reason;
      value = personalResult.value;
      const labels = { queries: "business.usageQuery", reports: "business.usageReports", exports_rows: "business.usageExport" };
      cards.innerHTML = Object.entries(value?.entitlements || {}).map(([key, item]) => {
        const limit = item.limit == null ? t("business.unknownLimit") : String(item.limit);
        return `<article class="business-card"><h3>${escapeHtml(t(labels[key] || key))}</h3><p>${escapeHtml(String(item.used ?? 0))} / ${escapeHtml(limit)}</p></article>`;
      }).join("") || `<p>${escapeHtml(t("business.usageUnavailable"))}</p>`;
      const period = value?.period;
      const periodElement = byId("usagePeriod");
      if (periodElement) periodElement.textContent = period ? `${t("business.period")}: ${period.start} → ${period.end}` : t("business.periodUnavailable");
      setNotice("usageNotice", value?.available === false ? t("business.sourceUnavailable") : t("business.usageLive"));
    }).catch((error) => {
      cards.textContent = t("business.usageUnavailable");
      setNotice("usageNotice", error?.status === 403 ? t("business.organizationForbidden") : t("business.usageUnavailable"));
    });
  }

  function renderSubscriptions() {
    const list = byId("subscriptionList");
    if (!list) return;
    list.textContent = t("business.loading");
    setNotice("subscriptionNotice", t("business.subscriptionsUnavailable"));
    if (!window.ZouBusinessApi) return;
    window.ZouBusinessApi.getSubscription().then((subscription) => {
      if (!subscription) {
        list.innerHTML = `<p>${escapeHtml(t("business.notSubscribed"))} · <a href="billing.html">${escapeHtml(t("business.upgrade"))}</a></p>`;
        setNotice("subscriptionNotice", t("business.subscriptionEmpty"));
        return;
      }
      list.innerHTML = `<div class="business-list-row"><strong>${escapeHtml(subscription.plan || t("business.notAvailable"))}</strong><span>${escapeHtml(t(`business.subscriptionStatus.${subscription.status}`, subscription.status))}</span><span>${escapeHtml(subscription.current_period_end || t("business.dateUnavailable"))}</span><span>${subscription.cancel_at_period_end ? escapeHtml(t("business.cancelAtPeriodEnd")) : escapeHtml(t("business.autoRenewActive"))}</span></div>`;
      setNotice("subscriptionNotice", t("business.subscriptionLive"));
    }).catch(() => {
      list.textContent = t("business.subscriptionsUnavailable");
      setNotice("subscriptionNotice", t("business.subscriptionsUnavailable"));
    });
  }

  function renderExports() {
    const list = byId("exportList");
    const form = byId("exportForm");
    const quota = byId("exportQuota");
    if (!list || !form || !quota) return;
    const submitButton = form.querySelector("button[type='submit']");
    list.textContent = t("business.loading");
    quota.textContent = t("business.loading");

    function renderHistory(items) {
      if (!items.length) {
        list.innerHTML = `<p class="business-panel-copy">${escapeHtml(t("business.noExports"))}</p>`;
        return;
      }
      list.innerHTML = items.map((item) => `
        <div class="business-list-row" data-export-row data-export-id="${escapeHtml(item.id)}">
          <div><strong>${escapeHtml(t("business.exportCsv"))}</strong><span>${escapeHtml(item.id)}</span></div>
          <div>${escapeHtml(t("business.exportRowsCount", "{count} 行").replace("{count}", String(item.row_count)))}</div>
          <div>${escapeHtml(item.status === "completed" ? t("business.exportStatusCompleted") : item.status)}</div>
          <div class="business-list-action"><span>${escapeHtml(item.created_at || "—")}</span><button class="business-button secondary" type="button" data-export-action="download" data-export-id="${escapeHtml(item.id)}">${escapeHtml(t("business.download"))}</button></div>
        </div>
      `).join("");
    }

    let organizationMode = false;
    let api = window.ZouBusinessApi;
    let initialLoad = null;
    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-export-action='download']");
      if (!button) return;
      api[organizationMode ? "downloadOrganizationExport" : "downloadExport"](button.dataset.exportId).then((blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `export-${button.dataset.exportId}.csv`;
        link.click();
        URL.revokeObjectURL(url);
      }).catch(() => setNotice("exportNotice", t("business.exportError")));
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submitButton?.disabled) return;
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = t("business.exportSubmitting");
      }
      try {
        if (initialLoad) await initialLoad;
        const result = await api[organizationMode ? "createOrganizationExport" : "createExport"]();
        setNotice("exportNotice", result?.reused ? t("business.exportReused") : t("business.exportCreated"));
        await load();
      } catch (error) {
        setNotice("exportNotice", error?.status === 403 ? t("business.organizationForbidden") : error?.status === 429 ? t("business.exportQuotaExceeded") : error?.status === 422 ? t("business.exportNoData") : t("business.exportError"));
      } finally {
        if (submitButton) {
          submitButton.disabled = false;
          submitButton.textContent = t("business.createExport");
        }
      }
    });

    async function load() {
      if (!window.ZouBusinessApi) {
        quota.textContent = t("business.exportError");
        list.textContent = t("business.noExports");
        return;
      }
      const [orgResult, usageResult, exportsResult] = await Promise.allSettled([window.ZouBusinessApi.getOrganization(), window.ZouBusinessApi.getUsageSummary(), window.ZouBusinessApi.listExports()]);
      organizationMode = orgResult.status === "fulfilled" && Boolean(orgResult.value?.organization);
      api = window.ZouBusinessApi;
      if (organizationMode) {
        const exportScope = byId("exportScope");
        if (exportScope) exportScope.textContent = t("business.organizationExportScope");
        const role = orgResult.value?.role;
        if (!["owner", "admin"].includes(role)) {
          form.hidden = true;
          setNotice("exportNotice", t("business.organizationForbidden"));
        }
        let orgUsage;
        let orgExports;
        try {
          [orgUsage, orgExports] = await Promise.all([window.ZouBusinessApi.getOrganizationUsage(), window.ZouBusinessApi.listOrganizationExports()]);
        } catch (error) {
          quota.textContent = t("business.exportQuotaUnavailable");
          list.textContent = error?.status === 403 ? t("business.organizationForbidden") : t("business.exportError");
          return;
        }
        const item = orgUsage?.entitlements?.exports_rows;
        quota.textContent = item ? format("business.exportQuotaRemaining", { remaining: Math.max(0, item.limit - item.used), limit: item.limit }) : t("business.exportQuotaUnavailable");
        renderHistory(orgExports?.exports || []);
        return;
      }
      if (usageResult.status === "fulfilled") {
        const item = usageResult.value?.entitlements?.exports_rows;
        const limit = item?.limit;
        const used = item?.used ?? 0;
        quota.textContent = limit == null ? t("business.exportQuotaUnavailable") : format("business.exportQuotaRemaining", { remaining: Math.max(0, limit - used), limit });
      } else quota.textContent = t("business.exportQuotaUnavailable");
      if (exportsResult.status === "fulfilled") renderHistory(exportsResult.value?.exports || []);
      else list.textContent = t("business.exportError");
    }

    initialLoad = load();
  }

  function renderServiceTasks() {
    const tasks = [
      { id: "TASK-001", type: "business.serviceAccompany", status: "open", area: "region.osaka", time: "business.earlySeptember", reward: "business.feeFrom15000", summary: "business.taskSummaryAccompany" },
      { id: "TASK-002", type: "business.serviceExpert", status: "in_progress", area: "region.tokyo", time: "business.midSeptember", reward: "business.negotiable", summary: "business.taskSummaryExpert" },
      { id: "TASK-003", type: "business.serviceRecommend", status: "completed", area: "region.yokohama", time: "business.lateAugust", reward: "business.fee8000", summary: "business.taskSummaryRecommend" },
    ];
    const list = byId("taskList");
    const filter = byId("taskFilter");
    if (!list || !filter) return;
    let currentFilter = "all";

    const statusMeta = {
      open: { key: "business.taskOpen", className: "pending" },
      applied: { key: "business.taskApplied", className: "active" },
      in_progress: { key: "business.taskInProgress", className: "active" },
      completed: { key: "business.taskCompleted", className: "" },
    };

    function render() {
      const visible = tasks.filter((task) => currentFilter === "all" || task.status === currentFilter);
      list.innerHTML = visible.map((task) => {
        const meta = statusMeta[task.status];
        const action = task.status === "open"
          ? `<button class="business-button" type="button" data-task-action="apply" data-task-id="${escapeHtml(task.id)}">${escapeHtml(t("business.apply"))}</button>`
          : task.status === "applied"
            ? `<button class="business-button secondary" type="button" data-task-action="withdraw" data-task-id="${escapeHtml(task.id)}">${escapeHtml(t("business.withdraw"))}</button>`
            : "";
        return `
          <article class="business-task-card" data-task-row data-task-id="${escapeHtml(task.id)}">
            <div class="business-panel-heading"><span class="business-status ${meta.className}">${escapeHtml(t(meta.key))}</span><span class="business-fixture-note">${escapeHtml(task.id)} · synthetic_fixture</span></div>
            <h3>${escapeHtml(t(task.type))}</h3>
            <p>${escapeHtml(t(task.summary, "C 端服务需求演示，不含个人联系方式。"))}</p>
            <dl class="business-task-facts"><div><dt>${escapeHtml(t("business.area"))}</dt><dd>${escapeHtml(t(task.area))}</dd></div><div><dt>${escapeHtml(t("business.time"))}</dt><dd>${escapeHtml(t(task.time))}</dd></div><div><dt>${escapeHtml(t("business.reward"))}</dt><dd>${escapeHtml(t(task.reward))}</dd></div><div><dt>${escapeHtml(t("business.taskType"))}</dt><dd>${escapeHtml(t(task.type))}</dd></div></dl>
            <div class="business-list-action">${action}<button class="business-button secondary" type="button" data-task-action="details" data-task-id="${escapeHtml(task.id)}">${escapeHtml(t("business.viewDetails"))}</button></div>
          </article>
        `;
      }).join("");
      if (!visible.length) list.innerHTML = `<p class="business-panel-copy">${escapeHtml(t("business.taskNoticeDetails"))}</p>`;
    }

    filter.addEventListener("change", () => {
      currentFilter = filter.value;
      render();
      const label = currentFilter === "all" ? t("business.all") : t(statusMeta[currentFilter]?.key || "business.all");
      setNotice("taskNotice", `${label} · ${t("business.serviceTasksCopy")}`);
    });

    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-task-action]");
      if (!button) return;
      const task = tasks.find((item) => item.id === button.dataset.taskId);
      if (!task) return;
      if (button.dataset.taskAction === "apply") {
        task.status = "applied";
        currentFilter = "applied";
        filter.value = currentFilter;
        render();
        setNotice("taskNotice", t("business.taskNoticeApplied"));
        return;
      }
      if (button.dataset.taskAction === "withdraw") {
        task.status = "open";
        currentFilter = "open";
        filter.value = currentFilter;
        render();
        setNotice("taskNotice", t("business.taskNoticeWithdrawn"));
        return;
      }
      setNotice("taskNotice", t("business.taskNoticeDetails"));
      const detail = byId("taskDetail");
      if (detail) detail.textContent = `${t("business.taskDetails")} · ${task.id} · ${t(task.type)} · ${t(task.area)}`;
    });

    render();
  }

  function init() {
    renderSideSummary();
  if (page === "organization") renderOrganization();
  if (page === "invite") renderInvite();
    if (page === "billing") renderBilling();
    if (page === "usage") renderUsage();
    if (page === "subscriptions") renderSubscriptions();
    if (page === "exports") renderExports();
    if (page === "service-tasks") renderServiceTasks();
    document.body.classList.add("business-page-ready");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();

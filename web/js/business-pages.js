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

  function renderOrganization() {
    const members = [
      { id: "MBR-001", name: "business.memberMain", role: "business.owner", state: "business.active", stateClass: "", last: "business.today" },
      { id: "MBR-002", name: "business.memberSeatA", role: "business.memberRole", state: "business.active", stateClass: "", last: "business.today" },
      { id: "MBR-003", name: "business.memberSeatB", role: "business.memberRole", state: "business.invited", stateClass: "pending", last: "business.yesterday" },
      { id: "MBR-004", name: "business.memberAudit", role: "business.memberRole", state: "business.active", stateClass: "", last: "business.yesterday" },
    ];
    const list = byId("organizationMembers");
    if (!list) return;

    list.innerHTML = members.map((member) => `
      <tr data-member-row data-member-id="${escapeHtml(member.id)}">
        <th scope="row">${escapeHtml(t(member.name))}<span class="business-table-subtext">${escapeHtml(member.id)} · synthetic_fixture</span></th>
        <td data-label="${escapeHtml(t("business.role"))}">${escapeHtml(t(member.role))}</td>
        <td data-label="${escapeHtml(t("business.status"))}">${status(member.state, member.stateClass)}</td>
        <td data-label="${escapeHtml(t("business.lastActive"))}">${escapeHtml(t(member.last))}</td>
        <td data-label="${escapeHtml(t("business.action"))}"><button class="business-button secondary" type="button" data-member-action="view" data-member-id="${escapeHtml(member.id)}">${escapeHtml(t("business.view"))}</button></td>
      </tr>
    `).join("");

    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-member-action]");
      if (!button) return;
      setNotice("organizationNotice", t("business.memberDetailNotice"));
      const detail = byId("organizationDetail");
      if (detail) detail.textContent = `${t("business.memberDetailNotice")} ${button.dataset.memberId}`;
    });

    byId("inviteMemberButton")?.addEventListener("click", () => {
      setNotice("organizationNotice", t("business.inviteNotice"));
    });
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
    Promise.allSettled([window.ZouBusinessApi.getBillingPrices(), window.ZouBusinessApi.getMe(), window.ZouBusinessApi.getSubscription()]).then(([pricesResult, meResult, subscriptionResult]) => {
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
    window.ZouBusinessApi.getUsageSummary().then((value) => {
      const labels = { queries: "business.usageQuery", reports: "business.usageReports", exports_rows: "business.usageExport" };
      cards.innerHTML = Object.entries(value?.entitlements || {}).map(([key, item]) => {
        const limit = item.limit == null ? t("business.unknownLimit") : String(item.limit);
        return `<article class="business-card"><h3>${escapeHtml(t(labels[key] || key))}</h3><p>${escapeHtml(String(item.used ?? 0))} / ${escapeHtml(limit)}</p></article>`;
      }).join("") || `<p>${escapeHtml(t("business.usageUnavailable"))}</p>`;
      const period = value?.period;
      const periodElement = byId("usagePeriod");
      if (periodElement) periodElement.textContent = period ? `${t("business.period")}: ${period.start} → ${period.end}` : t("business.periodUnavailable");
      setNotice("usageNotice", value?.available === false ? t("business.sourceUnavailable") : t("business.usageLive"));
    }).catch(() => {
      cards.textContent = t("business.usageUnavailable");
      setNotice("usageNotice", t("business.usageUnavailable"));
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

    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-export-action='download']");
      if (!button) return;
      window.ZouBusinessApi.downloadExport(button.dataset.exportId).then((blob) => {
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
      try {
        await window.ZouBusinessApi.createExport();
        setNotice("exportNotice", t("business.exportCreated"));
        await load();
      } catch (error) {
        const message = String(error?.message || "");
        setNotice("exportNotice", message.includes("429") ? t("business.exportQuotaExceeded") : message.includes("no owned reports") ? t("business.exportNoData") : t("business.exportError"));
      }
    });

    async function load() {
      if (!window.ZouBusinessApi) {
        quota.textContent = t("business.exportError");
        list.textContent = t("business.noExports");
        return;
      }
      const [usageResult, exportsResult] = await Promise.allSettled([window.ZouBusinessApi.getUsageSummary(), window.ZouBusinessApi.listExports()]);
      if (usageResult.status === "fulfilled") {
        const item = usageResult.value?.entitlements?.exports_rows;
        const limit = item?.limit;
        const used = item?.used ?? 0;
        quota.textContent = limit == null ? t("business.exportQuotaUnavailable") : format("business.exportQuotaRemaining", { remaining: Math.max(0, limit - used), limit });
      } else quota.textContent = t("business.exportQuotaUnavailable");
      if (exportsResult.status === "fulfilled") renderHistory(exportsResult.value?.exports || []);
      else list.textContent = t("business.exportError");
    }

    load();
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

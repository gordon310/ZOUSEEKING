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
    const text = format("business.seatSummary", { used: 4, total: 5 });
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
    const state = { currency: "CNY", plan: "pro", autoRenew: false };
    const prices = {
      CNY: { free: "0", pro: "199" },
      JPY: { free: "0", pro: "3,999" },
      USD: { free: "0", pro: "39.9" },
    };

    function currentPrice() {
      const price = prices[state.currency][state.plan];
      return state.plan === "free" ? price : `${price}`;
    }

    function render() {
      const planLabel = state.plan === "free" ? t("business.planFree") : t("business.planPro");
      const price = byId("billingPrice");
      if (price) price.textContent = `${currencyLabel(state.currency)} ${currentPrice()}${t("business.pricePerMonth")}`;
      const autoRenew = byId("autoRenewButton");
      if (autoRenew) {
        autoRenew.textContent = state.autoRenew ? t("business.autoRenewOn") : t("business.autoRenewOff");
        autoRenew.setAttribute("aria-pressed", String(state.autoRenew));
      }
      const currentPlan = byId("billingCurrentPlan");
      if (currentPlan) currentPlan.textContent = planLabel;

      const plans = byId("billingPlans");
      if (!plans) return;
      plans.innerHTML = [
        {
          id: "free",
          title: t("business.planFree"),
          copy: t("business.planFreeCopy"),
          price: `${currencyLabel(state.currency)} ${prices[state.currency].free}`,
          benefits: [
            [t("business.queryQuota"), `30 ${t("business.perMonth")}`],
            [t("business.analysisQuota"), `5 ${t("business.perMonth")}`],
            [t("business.noExport"), ""],
          ],
        },
        {
          id: "pro",
          title: t("business.planPro"),
          copy: t("business.planProCopy"),
          price: `${currencyLabel(state.currency)} ${prices[state.currency].pro}`,
          benefits: [
            [t("business.queryQuota"), `500 ${t("business.perMonth")}`],
            [t("business.analysisQuota"), `100 ${t("business.perMonth")}`],
            [t("business.subscriptionQuota"), t("business.subscriptionCountValue")],
            [t("business.exportQuota"), t("business.exportRowsValue")],
          ],
        },
      ].map((plan) => `
        <article class="business-card ${state.plan === plan.id ? "is-current" : ""}">
          <h3>${escapeHtml(plan.title)}</h3>
          <p>${escapeHtml(plan.copy)}</p>
          ${state.plan === plan.id ? `<span class="business-plan-badge">${escapeHtml(t("business.planCurrent"))}</span>` : ""}
          <div class="business-card-price"><strong>${escapeHtml(plan.price)}</strong><span>${escapeHtml(t("business.pricePerMonth"))}</span></div>
          <ul class="business-benefit-list">${plan.benefits.map(([label, value]) => `<li class="${value ? "" : "is-muted"}">${escapeHtml(label)}${value ? `：${escapeHtml(value)}` : ""}</li>`).join("")}</ul>
          <button class="business-button ${state.plan === plan.id ? "secondary" : ""}" type="button" data-plan="${escapeHtml(plan.id)}">${escapeHtml(state.plan === plan.id ? t("business.planCurrent") : t("business.planSelect"))}</button>
        </article>
      `).join("");
    }

    byId("billingCurrency")?.addEventListener("change", (event) => {
      state.currency = event.target.value;
      render();
      setNotice("billingNotice", format("business.currencyNotice", { currency: currencyLabel(state.currency) }));
    });

    byId("billingPlans")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-plan]");
      if (!button) return;
      state.plan = button.dataset.plan;
      render();
      setNotice("billingNotice", format("business.planNotice", { plan: state.plan === "free" ? t("business.planFree") : t("business.planPro") }));
    });

    byId("autoRenewButton")?.addEventListener("click", () => {
      state.autoRenew = !state.autoRenew;
      render();
      setNotice("billingNotice", format("business.autoRenewNotice", { status: state.autoRenew ? t("business.autoRenewOn") : t("business.autoRenewOff") }));
    });

    render();
  }

  function renderUsage() {
    const quotas = [
      { kind: "query", label: "business.usageQuery", used: 318, limit: 500, unit: "business.unitUse" },
      { kind: "analysis", label: "business.usageAnalysis", used: 42, limit: 100, unit: "business.unitUse" },
      { kind: "subscription", label: "business.usageSubscription", used: 6, limit: 10, unit: "business.unitItem" },
      { kind: "export", label: "business.usageExport", used: 2480, limit: 10000, unit: "business.unitRow" },
    ];
    const events = [
      { kind: "query", label: "business.usageQuery", amount: "1", unit: "business.unitUse", timeKey: "business.todayAt", time: "10:20" },
      { kind: "query", label: "business.usageQuery", amount: "1", unit: "business.unitUse", timeKey: "business.todayAt", time: "09:42" },
      { kind: "analysis", label: "business.usageAnalysis", amount: "1", unit: "business.unitUse", timeKey: "business.yesterdayAt", time: "16:10" },
      { kind: "subscription", label: "business.usageSubscription", amount: "1", unit: "business.unitItem", timeKey: "business.yesterdayAt", time: "11:30" },
      { kind: "export", label: "business.usageExport", amount: "500", unit: "business.unitRow", timeKey: "", time: "2026-08-27 14:08" },
    ];
    const cards = byId("usageCards");
    const list = byId("usageList");
    const filter = byId("usageFilter");
    if (!cards || !list || !filter) return;

    cards.innerHTML = quotas.map((quota) => {
      const ratio = Math.min(100, Math.round((quota.used / quota.limit) * 100));
      return `<article class="business-quota-card"><h3>${escapeHtml(t(quota.label))}</h3><div class="business-quota-value"><strong>${quota.used.toLocaleString()}</strong><span>/ ${quota.limit.toLocaleString()} ${escapeHtml(t(quota.unit))}</span></div><div class="business-progress" aria-label="${escapeHtml(`${t(quota.label)} ${ratio}%`)}"><span style="width:${ratio}%"></span></div><p>${escapeHtml(t("business.resetDate"))}</p></article>`;
    }).join("");

    function renderEvents() {
      const selected = filter.value;
      const filtered = selected === "all" ? events : events.filter((event) => event.kind === selected);
      list.innerHTML = `
        <div class="business-list-row business-list-header" aria-hidden="true"><div>${escapeHtml(t("business.event"))}</div><div>${escapeHtml(t("business.occurredAt"))}</div><div>${escapeHtml(t("business.amount"))}</div><div></div></div>
        ${filtered.map((event) => `<div class="business-list-row" data-usage-kind="${escapeHtml(event.kind)}"><div><strong>${escapeHtml(t(event.label))}</strong><span>synthetic_fixture</span></div><div><span>${escapeHtml(event.timeKey ? format(event.timeKey, { time: event.time }) : event.time)}</span></div><div><strong>${escapeHtml(event.amount)} ${escapeHtml(t(event.unit))}</strong></div><div></div></div>`).join("")}
      `;
      const kind = selected === "all" ? t("business.usageAll") : t(`business.usage${selected[0].toUpperCase()}${selected.slice(1)}`);
      setNotice("usageNotice", format("business.usageFilterNotice", { kind }));
    }

    filter.addEventListener("change", renderEvents);
    renderEvents();
  }

  function renderSubscriptions() {
    const subscriptions = [
      { id: "SUB-001", region: "region.tokyo", asset: "asset.tower", frequency: "business.everyWeek", active: true, next: "2026-09-01" },
      { id: "SUB-002", region: "region.osaka", asset: "asset.apartment", frequency: "business.everyMonth", active: true, next: "2026-09-05" },
      { id: "SUB-003", region: "region.yokohama", asset: "asset.detached", frequency: "business.everyMonth", active: false, next: "—" },
    ];
    const list = byId("subscriptionList");
    const form = byId("subscriptionForm");
    if (!list || !form) return;

    function label(subscription) {
      return `${t(subscription.region)} · ${t(subscription.asset)} · ${t(subscription.frequency)}`;
    }

    function render() {
      list.innerHTML = `
        <div class="business-list-row business-list-header" aria-hidden="true"><div>${escapeHtml(t("business.subscriptionName"))}</div><div>${escapeHtml(t("business.subscriptionStatus"))}</div><div>${escapeHtml(t("business.nextUpdate"))}</div><div>${escapeHtml(t("business.subscriptionAction"))}</div></div>
        ${subscriptions.map((subscription) => `
          <div class="business-list-row" data-subscription-row data-subscription-id="${escapeHtml(subscription.id)}">
            <div><strong>${escapeHtml(label(subscription))}</strong><span>${escapeHtml(subscription.id)} · synthetic_fixture</span></div>
            <div>${status(subscription.active ? "business.subscriptionActive" : "business.subscriptionPaused", subscription.active ? "" : "paused")}</div>
            <div><span>${escapeHtml(subscription.next)}</span></div>
            <div class="business-list-action"><button class="business-button secondary" type="button" data-subscription-action="toggle" data-subscription-id="${escapeHtml(subscription.id)}">${escapeHtml(t(subscription.active ? "business.pause" : "business.resume"))}</button><button class="business-button danger" type="button" data-subscription-action="delete" data-subscription-id="${escapeHtml(subscription.id)}">${escapeHtml(t("business.delete"))}</button></div>
          </div>
        `).join("")}
      `;
    }

    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-subscription-action]");
      if (!button) return;
      const index = subscriptions.findIndex((item) => item.id === button.dataset.subscriptionId);
      if (index < 0) return;
      if (button.dataset.subscriptionAction === "delete") {
        subscriptions.splice(index, 1);
        render();
        setNotice("subscriptionNotice", t("business.subscriptionNoticeDeleted"));
        return;
      }
      subscriptions[index].active = !subscriptions[index].active;
      render();
      setNotice("subscriptionNotice", format("business.subscriptionNoticeToggled", { status: t(subscriptions[index].active ? "business.subscriptionActive" : "business.subscriptionPaused") }));
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(form);
      subscriptions.push({
        id: `SUB-${String(Math.max(0, ...subscriptions.map((item) => Number(item.id.replace("SUB-", "")))) + 1).padStart(3, "0")}`,
        region: data.get("prefecture") || "region.tokyo",
        asset: data.get("assetType") || "asset.tower",
        frequency: data.get("frequency") || "business.everyMonth",
        active: true,
        next: "2026-09-08",
      });
      render();
      setNotice("subscriptionNotice", t("business.subscriptionNoticeAdded"));
    });

    render();
  }

  function renderExports() {
    const exports = [
      { id: "EXP-001", dataset: "business.datasetRegional", format: "CSV", rows: "500", status: "business.exportCompleted", statusClass: "", created: "2026-08-28 15:20" },
      { id: "EXP-002", dataset: "business.datasetTrend", format: "XLSX", rows: "1,000", status: "business.exportQueued", statusClass: "pending", created: "2026-08-29 09:05" },
    ];
    const list = byId("exportList");
    const form = byId("exportForm");
    if (!list || !form) return;

    function render() {
      list.innerHTML = `
        <div class="business-list-row business-list-header" aria-hidden="true"><div>${escapeHtml(t("business.dataset"))}</div><div>${escapeHtml(t("business.format"))}</div><div>${escapeHtml(t("business.exportStatus"))}</div><div>${escapeHtml(t("business.createdAt"))}</div></div>
        ${exports.map((item) => `
          <div class="business-list-row" data-export-row data-export-id="${escapeHtml(item.id)}">
            <div><strong>${escapeHtml(t(item.dataset))}</strong><span>${escapeHtml(item.id)} · ${escapeHtml(item.rows)} · synthetic_fixture</span></div>
            <div><span>${escapeHtml(item.format)}</span></div>
            <div>${status(item.status, item.statusClass)}</div>
            <div class="business-list-action">${item.status === "business.exportCompleted" ? `<button class="business-button secondary" type="button" data-export-action="view" data-export-id="${escapeHtml(item.id)}">${escapeHtml(t("business.viewDemo"))}</button>` : `<span>${escapeHtml(item.created)}</span>`}</div>
          </div>
        `).join("")}
      `;
    }

    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-export-action='view']");
      if (!button) return;
      setNotice("exportNotice", t("business.exportNotice"));
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(form);
      exports.push({
        id: `EXP-${String(exports.length + 1).padStart(3, "0")}`,
        dataset: data.get("dataset") || "business.datasetRegional",
        format: data.get("format") || "CSV",
        rows: data.get("rows") || "500",
        status: "business.exportQueued",
        statusClass: "pending",
        created: `${t("business.justNow")} · ${t("business.local")}`,
      });
      render();
      setNotice("exportNotice", t("business.exportNotice"));
    });

    render();
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

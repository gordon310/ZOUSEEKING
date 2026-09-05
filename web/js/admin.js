(() => {
  // Admin page controller. Coordinate-only: mode (admin-mode.js), the API
  // client (admin-api-client.js) and row/HTML builders + demo fixtures
  // (admin-views.js) live in their own modules. This file wires DOM events,
  // tab/section visibility and per-tab loaders.
  //
  // Demo remains the default surface. Live mode (ZouAdminMode.live) only
  // happens when an API base URL is configured AND the release boundary did
  // not mark the surface demo-only AND "?demo=1" is absent. Live tabs then
  // read GET /api/admin/* with the Supabase access token as Bearer; every
  // failure/403 path renders a visible state instead of demo data (demo rows
  // are never relabelled as real).

  const views = window.ZouAdminViews;
  const api = window.ZouAdminApi;
  const mode = window.ZouAdminMode;
  const isLive = Boolean(mode?.live && api && views);

  // ---- DOM refs -------------------------------------------------------------
  const tabs = Array.from(document.querySelectorAll("[data-admin-tab]"));
  const sections = Array.from(document.querySelectorAll("[data-admin-section]"));
  const statusFilter = document.querySelector("#adminStatusFilter");
  const notice = document.querySelector("#adminNotice");
  const detail = document.querySelector("#adminDetail");
  const detailHeading = document.querySelector("#adminDetailHeading");
  const memberSearch = document.querySelector("#memberSearch");
  const memberStatusFilter = document.querySelector("#memberStatusFilter");
  const memberStatusFilterLabel = memberStatusFilter?.closest("label");
  const memberList = document.querySelector("#memberList");
  const memberTableCaption = document.querySelector("#memberTableCaption");
  const memberTableHead = document.querySelector("#memberTableHead");
  const memberCount = document.querySelector("#memberCount");
  const memberNotice = document.querySelector("#memberNotice");
  const memberPager = document.querySelector("#memberPager");
  const memberLiveStatus = document.querySelector("#memberLiveStatus");
  const auditList = document.querySelector("#auditList");
  const auditCount = document.querySelector("#auditCount");
  const auditStatus = document.querySelector("#auditStatus");
  const auditNote = document.querySelector("#auditNote");
  const auditPager = document.querySelector("#auditPager");
  const auditActorFilter = document.querySelector("#auditActorFilter");
  const auditActionFilter = document.querySelector("#auditActionFilter");
  const auditSinceFilter = document.querySelector("#auditSinceFilter");
  const auditLimitFilter = document.querySelector("#auditLimitFilter");
  const orderStatusFilter = document.querySelector("#orderStatusFilter");
  const orderList = document.querySelector("#orderList");
  const orderTotals = document.querySelector("#orderTotals");
  const orderPager = document.querySelector("#orderPager");
  const financeStatus = document.querySelector("#financeStatus");
  const refundStatusFilter = document.querySelector("#refundStatusFilter");
  const refundList = document.querySelector("#refundList");
  const refundTotals = document.querySelector("#refundTotals");
  const refundPager = document.querySelector("#refundPager");
  const menuToggle = document.querySelector("#adminMenuToggle");
  const menu = document.querySelector("#adminMenu");
  const fixtureTag = document.querySelector("#adminFixtureTag");
  const fixtureLabel = document.querySelector("#adminFixtureLabel");
  const demoToolbarText = document.querySelector("#adminDemoToolbarText");
  const detailBoundary = document.querySelector("#adminDetailBoundary");
  const detailAuditMeta = document.querySelector("#adminDetailAuditMeta");
  const t = (key, fallback = "") =>
    window.ZouI18n && typeof window.ZouI18n.t === "function" ? window.ZouI18n.t(key, fallback) : fallback;

  const MEMBERS_COLSPAN = 7;

  // ---- shared state ---------------------------------------------------------
  const debounceTimers = {};
  function debounce(key, wait, fn) {
    window.clearTimeout(debounceTimers[key]);
    debounceTimers[key] = window.setTimeout(fn, wait);
  }

  function setText(node, text) {
    if (node) node.textContent = text;
  }

  function setStatus(node, text, kind = "") {
    if (!node) return;
    node.textContent = text;
    node.classList.toggle("is-error", kind === "error");
    node.classList.toggle("is-info", kind === "info");
  }

  function setGlobalNotice(text) {
    setText(notice, text);
  }

  function setMemberNotice(text) {
    setText(memberNotice, text);
    setText(notice, text);
  }

  function apiErrorMessage(error, rolesHint) {
    if (!error) return t("admin.errorUnknown", "加载失败，请稍后重试。");
    const status = Number(error.status);
    if (status === 401) {
      return t("admin.error401", "未检测到有效登录会话（Bearer 令牌缺失或已过期）。请先登录后台账号后刷新页面。");
    }
    if (status === 403) {
      return `${t("admin.error403", "当前账号无权访问该模块（403）。")}${rolesHint ? ` ${rolesHint}` : ""}`;
    }
    if (status === 503) {
      return t("admin.error503", "后台管理服务尚未启用（503）。服务开启后再刷新即可读取真实数据。");
    }
    if (status === 0) {
      return t("admin.errorNetwork", "无法连接后台服务：网络错误或服务不可达。");
    }
    const detail = error.message || "";
    return `${t("admin.errorHttp", "后台请求失败")}（HTTP ${status || "?"}）：${detail}`;
  }

  function notRealFallbackNote() {
    return t(
      "admin.noFakeFallback",
      "为避免把演示数据误标为真实，此处不展示本地数据；请修复后台连接后重试。",
    );
  }

  // ---- demo fixtures ---------------------------------------------------------
  function demoFilteredRows() {
    const query = (memberSearch?.value || "").trim().toLowerCase();
    const status = memberStatusFilter?.value || "all";
    return views.demoMembers.filter((row) => {
      const searchable = `${row.label} ${row.id} ${row.tier}`.toLowerCase();
      return (!query || searchable.includes(query)) && (status === "all" || row.status === status);
    });
  }

  function renderDemoMembers() {
    if (!memberList) return;
    setText(memberCount, "synthetic_fixture");
    memberList.innerHTML = views.demoMemberRowsHtml(demoFilteredRows());
    memberList.querySelectorAll("[data-member-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const row = views.demoMembers.find((item) => item.id === button.dataset.memberId);
        if (!row) return;
        if (button.dataset.memberAction === "view") {
          if (detail) detail.textContent = row.detail;
          setMemberNotice(`已查看 ${row.label} 的演示详情；真实会员字段仍需服务端授权。`);
          return;
        }
        row.status = row.status === "paused" ? "active" : "paused";
        setMemberNotice(`已在本地演示状态中${row.status === "paused" ? "暂停" : "恢复"} ${row.label}；没有修改真实会员资料。`);
        renderDemoMembers();
      });
    });
  }

  function syncMemberTableSchema() {
    if (!memberTableHead) return;
    memberTableHead.innerHTML = isLive ? views.memberLiveHeaders : views.memberDemoHeaders;
    if (memberTableCaption) {
      memberTableCaption.textContent = isLive
        ? "会员资料与额度（来自真实后台 /api/admin/members）"
        : "会员资料与额度状态（界面演示）";
    }
    if (memberStatusFilterLabel) memberStatusFilterLabel.hidden = isLive;
    if (memberPager) memberPager.hidden = !isLive;
  }

  // ---- live loaders ---------------------------------------------------------
  const liveState = {
    members: { busy: false, page: 1, pageSize: 20, total: 0 },
    audit: { busy: false, page: 1, pageSize: 100, total: 0 },
    orders: { busy: false, page: 1, pageSize: 20, total: 0 },
    refunds: { busy: false, page: 1, pageSize: 20, total: 0 },
  };

  async function loadLiveMembers(page = liveState.members.page) {
    if (!memberList || liveState.members.busy) return;
    liveState.members.busy = true;
    liveState.members.page = Math.max(1, page);
    setStatus(memberLiveStatus, t("admin.loading", "正在从后台加载……"));
    setText(memberCount, "…");
    if (memberPager) memberPager.innerHTML = "";
    memberList.innerHTML = views.loadingRow(MEMBERS_COLSPAN);
    try {
      const payload = await api.listMembers({
        q: (memberSearch?.value || "").trim(),
        page: liveState.members.page,
        page_size: liveState.members.pageSize,
      });
      liveState.members.total = Number(payload?.total) || 0;
      memberList.innerHTML = views.memberLiveRowsHtml(
        payload?.items || [],
        t("admin.writePending", "待后端写端点"),
      );
      if (memberPager) {
        memberPager.innerHTML = views.pagerHtml({
          page: liveState.members.page,
          pageSize: liveState.members.pageSize,
          total: liveState.members.total,
          target: "members",
        });
      }
      setText(memberCount, `${payload?.items?.length ?? 0} / ${liveState.members.total} 条`);
      setStatus(memberLiveStatus, t("admin.liveSource", "数据来源：真实后台"));
      setMemberNotice("");
    } catch (error) {
      const roles = isLive ? t("admin.rolesMemberOps", "需要 member_ops / super_admin 角色。") : "";
      memberList.innerHTML = "";
      if (memberPager) memberPager.innerHTML = "";
      setText(memberCount, "—");
      const message = `${apiErrorMessage(error, roles)}${notRealFallbackNote()}`;
      setStatus(memberLiveStatus, message, "error");
      setMemberNotice("");
    } finally {
      liveState.members.busy = false;
    }
  }

  async function showLiveMemberDetail(userId) {
    if (!detail || !userId) return;
    setText(detailHeading, "会员详情");
    detail.textContent = t("admin.loading", "正在从后台加载……");
    try {
      const member = await api.getMember(userId);
      detail.textContent = views.memberDetailText(member);
    } catch (error) {
      detail.textContent = apiErrorMessage(error, t("admin.rolesMemberOps", "需要 member_ops / super_admin 角色。"));
    }
  }

  async function loadLiveAudit(page = liveState.audit.page) {
    if (!auditList || liveState.audit.busy) return;
    liveState.audit.busy = true;
    liveState.audit.page = Math.max(1, page);
    setStatus(auditStatus, t("admin.loading", "正在从后台加载……"));
    setText(auditCount, "…");
    if (auditPager) auditPager.innerHTML = "";
    auditList.innerHTML = views.loadingRow(5);
    try {
      const sinceRaw = auditSinceFilter?.value || "";
      const since = sinceRaw ? new Date(sinceRaw).toISOString() : "";
      const payload = await api.listAudit({
        actor: (auditActorFilter?.value || "").trim(),
        action: (auditActionFilter?.value || "").trim(),
        since,
        limit: Number(auditLimitFilter?.value || 100),
      });
      const items = payload?.items || [];
      liveState.audit.total = items.length;
      auditList.innerHTML = views.auditRowsHtml(items);
      if (auditPager) auditPager.innerHTML = "";
      setText(auditCount, `${items.length} 条`);
      setStatus(
        auditStatus,
        items.length
          ? t("admin.liveSource", "数据来源：真实后台")
          : t("admin.emptyAudit", "没有符合条件的审计记录。"),
        items.length ? "" : "info",
      );
    } catch (error) {
      auditList.innerHTML = "";
      setText(auditCount, "—");
      const message = `${apiErrorMessage(error, t("admin.rolesAudit", "需要 member_ops（会员域）或 super_admin 角色。"))}${notRealFallbackNote()}`;
      setStatus(auditStatus, message, "error");
    } finally {
      liveState.audit.busy = false;
    }
  }

  async function loadLiveOrders(page = liveState.orders.page) {
    if (!orderList || liveState.orders.busy) return;
    liveState.orders.busy = true;
    liveState.orders.page = Math.max(1, page);
    setStatus(financeStatus, t("admin.loading", "正在从后台加载……"));
    setText(orderTotals, "…");
    if (orderPager) orderPager.innerHTML = "";
    orderList.innerHTML = views.loadingRow(7);
    try {
      const payload = await api.listOrders({
        status: orderStatusFilter?.value || "",
        page: liveState.orders.page,
        page_size: liveState.orders.pageSize,
      });
      liveState.orders.total = Number(payload?.total) || 0;
      orderList.innerHTML = views.orderRowsHtml(payload?.items || []);
      if (orderPager) {
        orderPager.innerHTML = views.pagerHtml({
          page: liveState.orders.page,
          pageSize: liveState.orders.pageSize,
          total: liveState.orders.total,
          target: "orders",
        });
      }
      setText(orderTotals, `共 ${liveState.orders.total} 笔 · 金额小计 ${orderSubtotalText(payload)}`);
      setStatus(financeStatus, t("admin.financeMinorNote", "金额按 ISO 货币最小单位换算展示（如 JPY 不分、USD 分）。"));
    } catch (error) {
      orderList.innerHTML = "";
      if (orderPager) orderPager.innerHTML = "";
      setText(orderTotals, "—");
      const message = `${apiErrorMessage(error, t("admin.rolesFinance", "需要 finance / super_admin 角色。"))}${notRealFallbackNote()}`;
      setStatus(financeStatus, message, "error");
    } finally {
      liveState.orders.busy = false;
    }
  }

  function orderSubtotalText(payload) {
    // Subtotal arrives as minor units without a single currency across rows;
    // show the raw number with an explicit label instead of guessing a
    // currency conversion across mixed-currencies.
    const minor = payload?.subtotal_amount_minor;
    return minor === null || minor === undefined || minor === "" ? "—" : `${minor}（minor units）`;
  }

  async function loadLiveRefunds(page = liveState.refunds.page) {
    if (!refundList || liveState.refunds.busy) return;
    liveState.refunds.busy = true;
    liveState.refunds.page = Math.max(1, page);
    setText(refundTotals, "…");
    if (refundPager) refundPager.innerHTML = "";
    refundList.innerHTML = views.loadingRow(6);
    try {
      const payload = await api.listRefunds({
        status: refundStatusFilter?.value || "",
        page: liveState.refunds.page,
        page_size: liveState.refunds.pageSize,
      });
      liveState.refunds.total = Number(payload?.total) || 0;
      refundList.innerHTML = views.refundRowsHtml(payload?.items || []);
      if (refundPager) {
        refundPager.innerHTML = views.pagerHtml({
          page: liveState.refunds.page,
          pageSize: liveState.refunds.pageSize,
          total: liveState.refunds.total,
          target: "refunds",
        });
      }
      setText(refundTotals, `共 ${liveState.refunds.total} 笔`);
    } catch (error) {
      refundList.innerHTML = "";
      if (refundPager) refundPager.innerHTML = "";
      setText(refundTotals, "—");
      const message = `${apiErrorMessage(error, t("admin.rolesFinance", "需要 finance / super_admin 角色。"))}${notRealFallbackNote()}`;
      setStatus(financeStatus, message, "error");
    } finally {
      liveState.refunds.busy = false;
    }
  }

  function onPagerClick(event) {
    const button = event.target.closest("[data-pager-dir]");
    if (!button || button.disabled) return;
    const pager = button.closest("[data-pager-target]");
    const target = pager?.dataset?.pagerTarget;
    const dir = button.dataset.pagerDir === "next" ? 1 : -1;
    if (target === "members") loadLiveMembers(liveState.members.page + dir);
    else if (target === "orders") loadLiveOrders(liveState.orders.page + dir);
    else if (target === "refunds") loadLiveRefunds(liveState.refunds.page + dir);
  }

  // ---- tabs & legacy demo interactions ---------------------------------------
  function applyTab(name) {
    const selected = name || "overview";
    tabs.forEach((tab) => {
      const active = tab.dataset.adminTab === selected;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    sections.forEach((section) => {
      const available = section.dataset.adminSection.split(" ");
      section.classList.toggle("is-hidden", selected !== "overview" && !available.includes(selected));
    });
  }

  function applyStatusFilter() {
    const selected = statusFilter?.value || "all";
    document.querySelectorAll("[data-admin-row]").forEach((row) => {
      row.classList.toggle("is-hidden", selected !== "all" && row.dataset.status !== selected);
    });
  }

  function setDetailFrom(element) {
    if (!detail || !element) return;
    const copy =
      element.dataset.detail ||
      element.querySelector("p")?.textContent ||
      element.querySelector("div span")?.textContent ||
      "已选择本地演示记录。";
    detail.textContent = copy;
  }

  function updateRowStatus(row, status, className, label) {
    if (!row) return;
    row.dataset.status = status;
    const statusNode = row.querySelector(".admin-table-status");
    if (statusNode) {
      statusNode.className = `admin-table-status ${className}`;
      statusNode.textContent = label;
    }
    const action = row.querySelector("[data-admin-action]");
    if (action) {
      action.disabled = true;
      action.textContent = `${label}（演示）`;
    }
    applyStatusFilter();
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => applyTab(tab.dataset.adminTab));
  });

  statusFilter?.addEventListener("change", applyStatusFilter);

  document.querySelectorAll("[data-admin-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const row = button.closest("[data-admin-row]");
      const item = row || button.closest("li") || button.closest(".admin-service-row");
      setDetailFrom(item);

      if (button.dataset.adminAction === "review") {
        updateRowStatus(row, "已完成", "status-complete", "已完成");
        setGlobalNotice("已在本地演示状态中标记为完成；真实审核仍需记录工作人员、时间和审计结果。");
        return;
      }
      if (button.dataset.adminAction === "retry") {
        updateRowStatus(row, "运行中", "status-active", "运行中");
        setGlobalNotice("已在本地演示状态中进入重试；真实重试需要由可靠 worker 执行并记录失败分类。");
        return;
      }
      if (button.dataset.adminAction === "assign") {
        const statusNode = item?.querySelector(".admin-table-status");
        if (statusNode) {
          statusNode.className = "admin-table-status status-active";
          statusNode.textContent = "进行中";
        }
        button.disabled = true;
        button.textContent = "已分配（演示）";
        setGlobalNotice("服务任务已在本地演示状态中分配；真实派单需要校验角色、归属和审计记录。");
        return;
      }
      setGlobalNotice("已查看本地演示详情；真实数据和敏感字段不会通过前端直接授权。");
    });
  });

  // ---- live member interactions (delegated) -----------------------------------
  memberList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-member-action]");
    if (!button) return;
    const userId = button.dataset.memberId;
    if (!isLive) return; // demo rows are bound individually in renderDemoMembers
    if (button.dataset.memberAction === "view") {
      if (detail) setText(detailHeading, "会员详情");
      showLiveMemberDetail(userId);
    }
  });

  // ---- filters / events --------------------------------------------------------
  memberSearch?.addEventListener("input", () => {
    if (isLive) {
      debounce("memberSearch", 350, () => loadLiveMembers(1));
    } else {
      renderDemoMembers();
    }
  });
  memberStatusFilter?.addEventListener("change", renderDemoMembers);

  auditActorFilter?.addEventListener("input", () => {
    debounce("auditActor", 400, () => loadLiveAudit(1));
  });
  auditActionFilter?.addEventListener("input", () => {
    debounce("auditAction", 400, () => loadLiveAudit(1));
  });
  auditSinceFilter?.addEventListener("change", () => loadLiveAudit(1));
  auditLimitFilter?.addEventListener("change", () => loadLiveAudit(1));

  orderStatusFilter?.addEventListener("change", () => loadLiveOrders(1));
  refundStatusFilter?.addEventListener("change", () => loadLiveRefunds(1));

  document.addEventListener("click", onPagerClick);

  menuToggle?.addEventListener("click", () => {
    const open = menuToggle.getAttribute("aria-expanded") === "true";
    menuToggle.setAttribute("aria-expanded", String(!open));
    if (menu) menu.hidden = open;
  });

  menu?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      menu.hidden = true;
      menuToggle?.setAttribute("aria-expanded", "false");
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu && !menu.hidden) {
      menu.hidden = true;
      menuToggle?.setAttribute("aria-expanded", "false");
      menuToggle?.focus();
    }
  });

  // ---- chrome copy per mode -----------------------------------------------------
  function applyModeChrome() {
    if (!isLive) {
      setText(memberNotice, "");
      setText(auditCount, "—");
      setText(auditStatus, "");
      setText(financeStatus, "");
      setText(orderTotals, "—");
      setText(refundTotals, "—");
      return;
    }
    setText(
      fixtureTag,
      t("admin.fixtureLive", "已接线真实后台 · member/audit/finance 实时"),
    );
    setText(
      fixtureLabel,
      t(
        "admin.fixtureLiveHeading",
        "会员、审计与财务页签读取真实后台；总览 / 采集 / 审核 / 派单仍为演示域（对应后端未实现），其中的按钮不会产生真实操作。",
      ),
    );
    if (demoToolbarText) {
      demoToolbarText.textContent = t(
        "admin.toolbarLive",
        "已配置 API_BASE_URL。会员 / 审计 / 财务页签请求 /api/admin/*（Bearer）；采集与任务页签标注待后端。",
      );
    }
    setGlobalNotice(
      t(
        "admin.noticeLive",
        "已连接真实后台：会员、审计、财务为只读实时数据。采集 / 审核 / 派单（总览）为演示域，等待对应后端实现；无写端点前，状态切换按钮禁用。403 表示当前登录账号缺少所需后台角色。",
      ),
    );
    setText(detailBoundary, t("admin.boundaryLive", "只读端点 · 写操作待后端"));
    setText(detailAuditMeta, t("admin.auditLive", "审计页签实时"));
    if (auditNote) {
      auditNote.textContent = t("admin.liveAuditNote", "筛选支持 actor（user_id）、action 前缀、since 与 limit。member_ops 仅能看到会员域审计，super_admin 可见全量。");
    }
    const financeNote = document.querySelector("#financeNote");
    if (financeNote) {
      financeNote.textContent = t("admin.financeMinorNote", "金额按 ISO 货币最小单位换算展示（如 JPY 不分、USD 分）。订单与退款均为只读。");
    }
  }

  // ---- init ----------------------------------------------------------------------
  const hashTab = window.location.hash.replace("#", "");
  applyTab(tabs.some((tab) => tab.dataset.adminTab === hashTab) ? hashTab : "overview");
  applyStatusFilter();
  syncMemberTableSchema();
  applyModeChrome();

  if (isLive) {
    loadLiveMembers(1);
    loadLiveAudit(1);
    loadLiveOrders(1);
    loadLiveRefunds(1);
  } else {
    renderDemoMembers();
  }
})();

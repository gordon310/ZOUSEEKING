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
  const roleList = document.querySelector("#roleList");
  const roleTableHead = document.querySelector("#roleTableHead");
  const roleCount = document.querySelector("#roleCount");
  const roleStatus = document.querySelector("#roleStatus");
  const roleNote = document.querySelector("#roleNote");
  const roleTableCaption = document.querySelector("#roleTableCaption");
  const roleGrantPanel = document.querySelector("#roleGrantPanel");
  const roleUserId = document.querySelector("#roleUserId");
  const roleSelect = document.querySelector("#roleSelect");
  const roleExpires = document.querySelector("#roleExpires");
  const roleNoteInput = document.querySelector("#roleGrantNote");
  const roleGrantBtn = document.querySelector("#roleGrantBtn");
  const collectionTabNote = document.querySelector("#collectionTabNote");
  const collectionCount = document.querySelector("#collectionCount");
  const collectionPanelNote = document.querySelector("#collectionPanelNote");
  const collectionStatus = document.querySelector("#collectionStatus");
  const collectionDemoWrap = document.querySelector("#collectionDemoWrap");
  const collectionLiveWrap = document.querySelector("#collectionLiveWrap");
  const collectionTableHead = document.querySelector("#collectionTableHead");
  const collectionList = document.querySelector("#collectionList");
  const collectionPager = document.querySelector("#collectionPager");
  const collectionStatusFilter = document.querySelector("#collectionStatusFilter");
  const collectionSourceFilter = document.querySelector("#collectionSourceFilter");
  const collectionEnqueuePanel = document.querySelector("#collectionEnqueuePanel");
  const collectionSourceKey = document.querySelector("#collectionSourceKey");
  const collectionSourceType = document.querySelector("#collectionSourceType");
  const collectionEnqueueBtn = document.querySelector("#collectionEnqueueBtn");
  const menuToggle = document.querySelector("#adminMenuToggle");
  const menu = document.querySelector("#adminMenu");
  const fixtureTag = document.querySelector("#adminFixtureTag");
  const fixtureLabel = document.querySelector("#adminFixtureLabel");
  const demoToolbarText = document.querySelector("#adminDemoToolbarText");
  const detailBoundary = document.querySelector("#adminDetailBoundary");
  const detailAuditMeta = document.querySelector("#adminDetailAuditMeta");
  const t = (key, fallback = "") =>
    window.ZouI18n && typeof window.ZouI18n.t === "function" ? window.ZouI18n.t(key, fallback) : fallback;

  const MEMBERS_COLSPAN = 8;

  // ---- shared state ---------------------------------------------------------
  const debounceTimers = {};
  function debounce(key, wait, fn) {
    window.clearTimeout(debounceTimers[key]);
    debounceTimers[key] = window.setTimeout(fn, wait);
  }

  function setText(node, text) {
    if (node) node.textContent = text;
  }

  function interp(text, params = {}) {
    return String(text).replace(/\{(\w+)\}/g, (match, key) =>
      Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : match,
    );
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

  // ---- member live write gate ----------------------------------------------
  // Members tab status writes (POST /api/admin/members/{user_id}/status) are
  // shown and enabled only when /api/admin/internal/me reports member_ops or
  // super_admin. Demo mode never resolves this gate and keeps its local
  // toggle fixtures untouched.
  const memberState = {
    booted: false,
    busy: false,
    canWrite: false,
    roles: [],
  };

  function memberGateRolesHint() {
    return t(
      "admin.memberWriteBlocked",
      "需要 member_ops / super_admin 角色才能停用/恢复会员。",
    );
  }

  async function ensureMemberGate() {
    if (!isLive || memberState.booted || memberState.busy) return;
    memberState.booted = true;
    memberState.busy = true;
    try {
      const me = await api.getMe();
      const roles = Array.isArray(me?.roles) ? me.roles.map(String) : [];
      memberState.roles = roles;
      memberState.canWrite = roles.includes("member_ops") || roles.includes("super_admin");
    } catch (error) {
      // /me failures (401/403/503) leave the buttons disabled with the role
      // hint; the members list loader reports the underlying problem itself.
      memberState.canWrite = false;
    } finally {
      memberState.busy = false;
    }
  }

  async function ensureMemberTabData() {
    if (!isLive || !memberList) return;
    if (memberState.booted) {
      if (!memberState.busy) loadLiveMembers(liveState.members.page); // re-open refreshes
      return;
    }
    await ensureMemberGate();
    if (!memberState.busy) loadLiveMembers(1);
  }

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
      memberList.innerHTML = views.memberLiveRowsHtml(payload?.items || [], {
        canWrite: memberState.canWrite,
        statusTexts: {
          active: t("admin.memberStatusActive", "正常"),
          suspended: t("admin.memberStatusSuspended", "已停用"),
        },
        suspendLabel: t("admin.memberSuspend", "停用"),
        resumeLabel: t("admin.memberResume", "恢复"),
        writeBlockedTitle: memberGateRolesHint(),
      });
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

  // ---- member status writes (live, audited) ---------------------------------

  function memberStatusWriteErrorText(error) {
    const status = Number(error?.status);
    if (status === 403) {
      return `${t("admin.error403", "当前账号无权访问该模块（403）。")} ${memberGateRolesHint()}`;
    }
    if (status === 404) {
      return t("admin.memberStatusMissing", "会员不存在或已被删除（404），未做任何变更。");
    }
    if (status === 400) {
      return `${t("admin.errorHttp", "后台请求失败")}（400）：${error?.message || ""}`;
    }
    const detail = error?.message || "";
    return `${t("admin.errorHttp", "后台请求失败")}（HTTP ${status || "?"}）：${detail}`;
  }

  async function submitMemberStatusChange(userId, action) {
    if (!userId || !memberState.canWrite) return;
    const suspend = action === "suspend";
    const targetStatus = suspend ? "suspended" : "active";
    const confirmed = window.confirm(
      suspend
        ? t("admin.memberSuspendConfirm", "确认停用该会员？立即生效并写入审计。")
        : t("admin.memberResumeConfirm", "确认恢复该会员？立即生效并写入审计。"),
    );
    if (!confirmed) return;
    const label = suspend
      ? t("admin.memberStatusSuspended", "已停用")
      : t("admin.memberStatusActive", "正常");
    try {
      await api.setMemberStatus(userId, targetStatus);
      await loadLiveMembers(liveState.members.page); // refresh reflects new status
      setMemberNotice(
        interp(
          t("admin.memberStatusNotice", "已将会员状态改为“{status}”（{name}），审计已记录。"),
          { status: label, name: shortName(userId) },
        ),
      );
      if (detail) setText(detailHeading, "会员详情");
    } catch (error) {
      setMemberNotice(memberStatusWriteErrorText(error));
    }
  }

  function shortName(userId) {
    return String(userId || "").slice(0, 8);
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

  // ---- live roles (internal role assignments) -------------------------------
  const ROLES_COLSPAN = 7;
  const roleState = {
    booted: false,
    busy: false,
    canManage: false,
    currentUserId: "",
    roles: [],
  };

  function roleGateText() {
    return t("admin.rolesGate", "需要 super_admin 角色。");
  }

  function roleStatusHint() {
    if (!roleState.roles.length) {
      return t(
        "admin.roleNoAccess",
        "当前账号没有任何后台角色，无法查看或分配内部角色。",
      );
    }
    return interp(
      t(
        "admin.roleNoPermissionHint",
        "仅 super_admin 可查看与分配内部角色；当前账号角色：{roles}。",
      ),
      { roles: roleState.roles.join("、") },
    );
  }

  function setRolePanelVisible(visible) {
    if (!roleGrantPanel) return;
    roleGrantPanel.hidden = !visible;
    // .member-toolbar display rules would override the hidden attribute, so
    // toggle inline display as well.
    roleGrantPanel.style.display = visible ? "" : "none";
  }

  async function ensureRoleTabData() {
    if (!isLive || !roleList) return;
    if (roleState.booted) {
      if (roleState.canManage && !roleState.busy) loadLiveRoles(); // re-open refreshes
      return;
    }
    roleState.booted = true;
    await bootstrapRoleTab();
  }

  async function bootstrapRoleTab() {
    if (roleState.busy) return;
    roleState.busy = true;
    setText(roleCount, "…");
    setStatus(roleStatus, t("admin.loading", "正在从后台加载……"));
    if (roleList) roleList.innerHTML = views.loadingRow(ROLES_COLSPAN);
    let canManage = false;
    try {
      const me = await api.getMe();
      const roles = Array.isArray(me?.roles) ? me.roles.map(String) : [];
      roleState.currentUserId = String(me?.user_id || "");
      roleState.roles = roles;
      roleState.canManage = roles.includes("super_admin");
      canManage = roleState.canManage;
      if (!canManage) {
        // No super_admin: no list, no controls - honest hint only.
        setRolePanelVisible(false);
        renderRoleListState({ hint: roleStatusHint(), info: true });
      } else {
        setRolePanelVisible(true);
      }
    } catch (error) {
      roleState.canManage = false;
      renderRoleListState({
        hint: `${apiErrorMessage(error, roleGateText())}${notRealFallbackNote()}`,
        error: true,
      });
    } finally {
      roleState.busy = false;
    }
    if (canManage) await loadLiveRoles();
  }

  function renderRoleListState({ hint, error = false, info = false } = {}) {
    if (roleTableHead && views.ROLE_HEADERS) roleTableHead.innerHTML = views.ROLE_HEADERS;
    if (roleList) roleList.innerHTML = "";
    setText(roleCount, "—");
    if (roleNote) {
      roleNote.textContent = t(
        "admin.roleListLiveNote",
        "角色分配实时写入 internal_role_assignments 并记录审计；撤销自己的 super_admin 会被后端拒绝（需另一位 super_admin 或人工处理）。",
      );
    }
    if (roleTableCaption) {
      roleTableCaption.textContent = "内部角色分配（仅 super_admin 可见与操作）";
    }
    if (hint) setStatus(roleStatus, hint, error ? "error" : info ? "info" : "");
  }

  async function loadLiveRoles(keepStatus = false) {
    if (!roleList || roleState.busy) return;
    roleState.busy = true;
    if (roleTableHead && views.ROLE_HEADERS) roleTableHead.innerHTML = views.ROLE_HEADERS;
    if (!keepStatus) {
      setText(roleCount, "…");
      setStatus(roleStatus, t("admin.loading", "正在从后台加载……"));
    }
    roleList.innerHTML = views.loadingRow(ROLES_COLSPAN);
    try {
      const payload = await api.listRoles();
      const items = payload?.items || [];
      roleList.innerHTML = views.roleRowsHtml(items, {
        canManage: roleState.canManage,
        currentUserId: roleState.currentUserId,
        revokeLabel: t("admin.roleRevoke", "撤销"),
        selfBlockedTitle: t(
          "admin.roleSelfBlocked",
          "不能撤销自己的 super_admin（需另一 super_admin 或人工处理）",
        ),
        expiredLabel: "已过期",
      });
      setText(roleCount, `${items.length} 条`);
      if (!keepStatus) {
        setStatus(
          roleStatus,
          items.length ? t("admin.liveSource", "数据来源：真实后台") : t("admin.emptyRoles", "暂无角色分配记录。"),
          items.length ? "" : "info",
        );
      }
      if (roleNote) {
        roleNote.textContent = t(
          "admin.roleListLiveNote",
          "角色分配实时写入 internal_role_assignments 并记录审计；撤销自己的 super_admin 会被后端拒绝（需另一位 super_admin 或人工处理）。",
        );
      }
      if (roleTableCaption) {
        roleTableCaption.textContent = "内部角色分配（写入 internal_role_assignments，全程审计）";
      }
    } catch (error) {
      roleList.innerHTML = "";
      setText(roleCount, "—");
      setStatus(
        roleStatus,
        `${apiErrorMessage(error, roleGateText())}${notRealFallbackNote()}`,
        "error",
      );
    } finally {
      roleState.busy = false;
    }
  }

  function roleGrantInput() {
    const user = (roleUserId?.value || "").trim();
    if (!user) {
      setStatus(roleStatus, t("admin.roleNeedUserId", "请先填写目标用户 user_id。"), "error");
      roleUserId?.focus();
      return null;
    }
    const role = roleSelect?.value || "";
    if (!role) {
      setStatus(roleStatus, t("admin.roleNeedRole", "请选择角色。"), "error");
      return null;
    }
    let expiresIso = "";
    if (roleExpires?.value) {
      const when = new Date(roleExpires.value);
      if (!Number.isFinite(when.getTime()) || when.getTime() <= Date.now()) {
        setStatus(roleStatus, t("admin.roleInvalidExpiry", "过期时间须为未来时间。"), "error");
        return null;
      }
      expiresIso = when.toISOString();
    }
    return { user_id: user, role, note: (roleNoteInput?.value || "").trim(), expires_at: expiresIso };
  }

  function roleWriteErrorText(error) {
    const status = Number(error?.status);
    if (status === 403) {
      return `${t("admin.error403", "当前账号无权访问该模块（403）。")} ${roleGateText()}`;
    }
    if (status === 409) {
      return t("admin.roleDuplicate", "该用户已持有此角色（409）。如需重新分配请先撤销。");
    }
    const detail = error?.message || "";
    return `${t("admin.errorHttp", "后台请求失败")}（HTTP ${status || "?"}）：${detail}`;
  }

  async function submitRoleGrant() {
    if (!roleState.canManage || !roleGrantBtn) return;
    const payload = roleGrantInput();
    if (!payload) return;
    roleGrantBtn.disabled = true;
    setStatus(roleStatus, t("admin.loading", "正在从后台加载……"));
    try {
      await api.grantRole(payload);
      if (roleUserId) roleUserId.value = "";
      if (roleExpires) roleExpires.value = "";
      if (roleNoteInput) roleNoteInput.value = "";
      setStatus(
        roleStatus,
        interp(
          t("admin.roleGrantedNotice", "已授予 {role}（user_id：{user}），审计已记录。"),
          { role: payload.role, user: payload.user_id },
        ),
        "info",
      );
      await loadLiveRoles(true);
    } catch (error) {
      setStatus(roleStatus, roleWriteErrorText(error), "error");
    } finally {
      roleGrantBtn.disabled = false;
    }
  }

  async function submitRoleRevoke(userId, role) {
    if (!roleState.canManage || !userId || !role) return;
    const confirmed = window.confirm(
      t("admin.roleRevokeConfirm", "确认撤销该用户的此角色？立即生效并写入审计。"),
    );
    if (!confirmed) return;
    setStatus(roleStatus, t("admin.loading", "正在从后台加载……"));
    try {
      await api.revokeRole(userId, role);
      setStatus(
        roleStatus,
        interp(
          t("admin.roleRevokedNotice", "已撤销 {role}（user_id：{user}），审计已记录。"),
          { role, user: userId },
        ),
        "info",
      );
      await loadLiveRoles(true);
    } catch (error) {
      const detail = error?.message || "";
      if (Number(error?.status) === 400 && detail) {
        setStatus(roleStatus, detail, "error");
      } else {
        setStatus(roleStatus, roleWriteErrorText(error), "error");
      }
    }
  }

  // ---- live collection runs (collection_runs, data_ops/super_admin) ------
  const COLLECTION_COLSPAN = 8;
  const collectionState = {
    booted: false,
    busy: false,
    active: false,
    page: 1,
    pageSize: 20,
    total: 0,
    roles: [],
  };

  // Demo table stays visible only in demo mode; the live surface is used for
  // every live state (loading rows, real runs or a role-gate hint).
  function applyCollectionMode(mode) {
    if (!collectionDemoWrap || !collectionLiveWrap) return;
    const demoVisible = mode === "demo";
    const liveVisible = mode === "live";
    collectionDemoWrap.hidden = !demoVisible;
    collectionDemoWrap.style.display = demoVisible ? "" : "none";
    collectionLiveWrap.hidden = !liveVisible;
    collectionLiveWrap.style.display = liveVisible ? "" : "none";
  }

  function collectionGateText() {
    return t("admin.rolesCollection", "需要 data_ops / super_admin 角色。");
  }

  function collectionRoleHint() {
    if (!collectionState.roles.length) {
      return t(
        "admin.collectionNoAccess",
        "当前账号没有任何后台角色，无法查看采集任务。",
      );
    }
    return interp(
      t(
        "admin.collectionNoPermissionHint",
        "采集任务页签需要 data_ops / super_admin 角色；当前账号角色：{roles}。",
      ),
      { roles: collectionState.roles.join("、") },
    );
  }

  function setCollectionEnqueueVisible(visible) {
    if (!collectionEnqueuePanel) return;
    collectionEnqueuePanel.hidden = !visible;
    // .member-toolbar display rules would override the hidden attribute, so
    // toggle inline display as well (same pattern as the role grant panel).
    collectionEnqueuePanel.style.display = visible ? "" : "none";
  }

  function showCollectionLoading() {
    if (collectionTableHead) collectionTableHead.innerHTML = views.collectionLiveHeaders;
    if (collectionList) collectionList.innerHTML = views.loadingRow(COLLECTION_COLSPAN);
    setText(collectionCount, "…");
    if (collectionPager) collectionPager.innerHTML = "";
  }

  async function ensureCollectionTabData() {
    if (!isLive || !collectionList) return;
    if (collectionState.booted) {
      // Re-opening the tab refreshes the list when the caller has access.
      if (collectionState.active && !collectionState.busy) loadLiveCollectionRuns();
      return;
    }
    collectionState.booted = true;
    await bootstrapCollectionTab();
  }

  async function bootstrapCollectionTab() {
    if (collectionState.busy) return;
    collectionState.busy = true;
    applyCollectionMode("live");
    setStatus(collectionStatus, t("admin.loading", "正在从后台加载……"));
    showCollectionLoading();
    let active = false;
    try {
      const me = await api.getMe();
      const roles = Array.isArray(me?.roles) ? me.roles.map(String) : [];
      collectionState.roles = roles;
      active = roles.includes("data_ops") || roles.includes("super_admin");
      collectionState.active = active;
      if (collectionPanelNote) {
        collectionPanelNote.textContent = active
          ? t(
              "admin.collectionLiveNote",
              "列表读取真实后台 /api/admin/collection/runs（只读）：状态、行数、快照哈希、错误与时间来自 collection_runs。发起采集会入队 queued 并写入审计 admin.collection.queued（仅 data_ops / super_admin）；worker 执行器接入前任务保持 queued，不会自动执行。",
            )
          : t(
              "admin.collectionGateNote",
              "采集任务页签仅对 data_ops / super_admin 展示真实运行记录；其他角色不读取该后台数据。",
            );
      }
      if (!active) {
        setCollectionEnqueueVisible(false);
        setText(collectionCount, "—");
        if (collectionTableHead) collectionTableHead.innerHTML = "";
        if (collectionList) collectionList.innerHTML = "";
        applyCollectionMode("hidden");
        setStatus(collectionStatus, collectionRoleHint(), "info");
        return;
      }
      setCollectionEnqueueVisible(true);
    } catch (error) {
      collectionState.active = false;
      setCollectionEnqueueVisible(false);
      if (collectionTableHead) collectionTableHead.innerHTML = "";
      if (collectionList) collectionList.innerHTML = "";
      setText(collectionCount, "—");
      applyCollectionMode("hidden");
      setStatus(
        collectionStatus,
        `${apiErrorMessage(error, collectionGateText())}${notRealFallbackNote()}`,
        "error",
      );
      return;
    } finally {
      collectionState.busy = false;
    }
    if (active) await loadLiveCollectionRuns(1);
  }

  async function loadLiveCollectionRuns(page = collectionState.page, keepStatus = false) {
    if (!collectionList || collectionState.busy || !collectionState.active) return;
    collectionState.busy = true;
    collectionState.page = Math.max(1, page);
    if (!keepStatus) {
      setStatus(collectionStatus, t("admin.loading", "正在从后台加载……"));
      collectionList.innerHTML = views.loadingRow(COLLECTION_COLSPAN);
    }
    setText(collectionCount, "…");
    if (collectionPager) collectionPager.innerHTML = "";
    try {
      const payload = await api.listCollectionRuns({
        status: collectionStatusFilter?.value || "",
        source_key: (collectionSourceFilter?.value || "").trim(),
        page: collectionState.page,
        page_size: collectionState.pageSize,
      });
      collectionState.total = Number(payload?.total) || 0;
      const items = payload?.items || [];
      collectionList.innerHTML = views.collectionRunsHtml(items);
      if (collectionPager) {
        collectionPager.innerHTML = views.pagerHtml({
          page: collectionState.page,
          pageSize: collectionState.pageSize,
          total: collectionState.total,
          target: "collection",
        });
      }
      setText(collectionCount, `${items.length} / ${collectionState.total} 条`);
      if (!keepStatus) {
        setStatus(
          collectionStatus,
          items.length
            ? t("admin.liveSource", "数据来源：真实后台")
            : t("admin.emptyRuns", "暂无采集运行记录。"),
          items.length ? "" : "info",
        );
      }
    } catch (error) {
      collectionList.innerHTML = "";
      if (collectionPager) collectionPager.innerHTML = "";
      setText(collectionCount, "—");
      const message = `${apiErrorMessage(error, collectionGateText())}${notRealFallbackNote()}`;
      setStatus(collectionStatus, message, "error");
    } finally {
      collectionState.busy = false;
    }
  }

  function collectionWriteErrorText(error) {
    const status = Number(error?.status);
    if (status === 403) {
      return `${t("admin.error403", "当前账号无权访问该模块（403）。")} ${collectionGateText()}`;
    }
    const detail = error?.message || "";
    return `${t("admin.errorHttp", "后台请求失败")}（HTTP ${status || "?"}）：${detail}`;
  }

  async function submitCollectionEnqueue() {
    if (!collectionState.active || !collectionEnqueueBtn) return;
    const sourceKey = (collectionSourceKey?.value || "").trim();
    if (!sourceKey) {
      setStatus(collectionStatus, t("admin.collectionNeedSourceKey", "请先填写来源 source_key。"), "error");
      collectionSourceKey?.focus();
      return;
    }
    const sourceType = collectionSourceType?.value || "";
    if (!views.COLLECTION_SOURCE_TYPES.includes(sourceType)) {
      setStatus(collectionStatus, t("admin.collectionNeedSourceType", "请选择来源类型。"), "error");
      return;
    }
    collectionEnqueueBtn.disabled = true;
    setStatus(collectionStatus, t("admin.loading", "正在从后台加载……"));
    try {
      await api.enqueueCollectionRun({ source_key: sourceKey, source_type: sourceType });
      if (collectionSourceKey) collectionSourceKey.value = "";
      setStatus(
        collectionStatus,
        interp(
          t(
            "admin.collectionQueuedNotice",
            "已发起采集：{source_key}（{source_type}）已入队（queued），审计已记录。",
          ),
          { source_key: sourceKey, source_type: sourceType },
        ),
        "info",
      );
      await loadLiveCollectionRuns(1, true);
    } catch (error) {
      setStatus(collectionStatus, collectionWriteErrorText(error), "error");
    } finally {
      collectionEnqueueBtn.disabled = false;
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
    else if (target === "collection") loadLiveCollectionRuns(collectionState.page + dir);
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
    tab.addEventListener("click", () => {
      applyTab(tab.dataset.adminTab);
      if (tab.dataset.adminTab === "roles") ensureRoleTabData();
      if (tab.dataset.adminTab === "members") ensureMemberTabData();
      if (tab.dataset.adminTab === "collection") ensureCollectionTabData();
    });
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
      return;
    }
    if (button.disabled) return;
    const action = button.dataset.memberAction;
    if (action === "suspend" || action === "resume") {
      submitMemberStatusChange(userId, action);
    }
  });

  roleGrantBtn?.addEventListener("click", () => {
    if (isLive) submitRoleGrant();
  });

  roleList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-role-action]");
    if (!button || !isLive || button.disabled) return;
    const userId = button.dataset.roleUser;
    const role = button.dataset.roleName;
    if (button.dataset.roleAction === "revoke") submitRoleRevoke(userId, role);
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

  collectionStatusFilter?.addEventListener("change", () => loadLiveCollectionRuns(1));
  collectionSourceFilter?.addEventListener("input", () => {
    debounce("collectionSource", 400, () => loadLiveCollectionRuns(1));
  });
  collectionEnqueueBtn?.addEventListener("click", () => {
    if (isLive && collectionState.active) submitCollectionEnqueue();
  });

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
      applyCollectionMode("demo");
      setText(memberNotice, "");
      setText(auditCount, "—");
      setText(auditStatus, "");
      setText(financeStatus, "");
      setText(orderTotals, "—");
      setText(refundTotals, "—");
      return;
    }
    if (collectionTabNote) collectionTabNote.hidden = true;
    setText(
      fixtureTag,
      t(
        "admin.fixtureLive",
        "已接线真实后台 · member 可停用/恢复 · audit/finance/collection 实时 · roles 可分配/撤销 · 采集可入队",
      ),
    );
    setText(
      fixtureLabel,
      t(
        "admin.fixtureLiveHeading",
        "会员页签读取真实后台并支持停用/恢复会员（member_ops / super_admin，写入审计）；审计、财务页签读取真实后台；采集页签展示真实采集运行记录（data_ops / super_admin 可发起采集，写入审计）；内部角色页签支持真实分配与撤销（写入审计）。审核 / 派单仍为演示域（对应后端未实现），其中的按钮不会产生真实操作。",
      ),
    );
    if (demoToolbarText) {
      demoToolbarText.textContent = t(
        "admin.toolbarLive",
        "已配置 API_BASE_URL。会员 / 审计 / 财务 / 采集页签请求 /api/admin/*（Bearer）；会员页签在 member_ops / super_admin 下可停用/恢复；内部角色页签在 super_admin 下可真实分配与撤销；采集入队在 data_ops / super_admin 下写入 collection_runs 并记录审计。",
      );
    }
    setGlobalNotice(
      t(
        "admin.noticeLive",
        "已连接真实后台：会员页签支持停用/恢复会员（写 /api/admin/members/{user_id}/status 并记录审计 admin.member.status_changed，member_ops / super_admin）；审计、财务为只读实时数据；采集页签展示真实采集运行记录，data_ops / super_admin 可发起采集（入队 queued 并写入审计 admin.collection.queued）；内部角色页签可真实分配/撤销并写入审计（super_admin 专属，且不能撤销自己的 super_admin）。审核 / 派单（总览）为演示域。403 表示当前登录账号缺少所需后台角色。",
      ),
    );
    setText(
      detailBoundary,
      t(
        "admin.boundaryLive",
        "member/audit/finance/collection 只读 + 会员状态写端点（member_ops / super_admin）+ roles 分配写端点（super_admin）+ 采集入队写端点（data_ops / super_admin）",
      ),
    );
    setText(detailAuditMeta, t("admin.auditLive", "审计页签实时"));
    const memberPanelNote = document.querySelector("#memberPanelNote");
    if (memberPanelNote) {
      memberPanelNote.textContent = t(
        "admin.memberLiveNote",
        "列表读取真实后台 /api/admin/members（只读）；停用/恢复调用 POST /api/admin/members/{user_id}/status 并写入审计（member_ops / super_admin 可见可用）。",
      );
    }
    if (collectionPanelNote) {
      collectionPanelNote.textContent = t(
        "admin.collectionLiveNote",
        "列表读取真实后台 /api/admin/collection/runs（只读）：状态、行数、快照哈希、错误与时间来自 collection_runs。发起采集会入队 queued 并写入审计 admin.collection.queued（仅 data_ops / super_admin）；worker 执行器接入前任务保持 queued，不会自动执行。",
      );
    }
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
    // The member write gate resolves from /api/admin/internal/me before the
    // first members render so suspend/resume buttons are correctly enabled
    // (member_ops/super_admin) or disabled with the role hint from the start.
    ensureMemberGate().finally(() => {
      if (!liveState.members.busy) loadLiveMembers(1);
    });
    loadLiveAudit(1);
    loadLiveOrders(1);
    loadLiveRefunds(1);
    bootstrapCollectionTab();
  } else {
    renderDemoMembers();
  }
})();

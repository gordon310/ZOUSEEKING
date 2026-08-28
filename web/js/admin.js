(() => {
  const tabs = Array.from(document.querySelectorAll("[data-admin-tab]"));
  const sections = Array.from(document.querySelectorAll("[data-admin-section]"));
  const statusFilter = document.querySelector("#adminStatusFilter");
  const notice = document.querySelector("#adminNotice");
  const detail = document.querySelector("#adminDetail");
  const memberSearch = document.querySelector("#memberSearch");
  const memberStatusFilter = document.querySelector("#memberStatusFilter");
  const memberList = document.querySelector("#memberList");
  const memberNotice = document.querySelector("#memberNotice");
  const menuToggle = document.querySelector("#adminMenuToggle");
  const menu = document.querySelector("#adminMenu");

  const memberRows = [
    {
      id: "MBR-001",
      label: "演示会员 A",
      tier: "专业版",
      status: "active",
      quota: "18 / 30 次",
      activity: "今日 10:42",
      detail: "演示会员 A 当前为专业版，最近查看了东京港区的物件统计。此行不对应真实账户。",
    },
    {
      id: "MBR-002",
      label: "演示会员 B",
      tier: "基础版",
      status: "review",
      quota: "4 / 10 次",
      activity: "昨日 16:18",
      detail: "演示会员 B 的会员资料等待工作人员确认。真实等级、额度和状态必须由后端权限路径决定。",
    },
    {
      id: "MBR-003",
      label: "演示会员 C",
      tier: "专业版",
      status: "paused",
      quota: "0 / 30 次",
      activity: "2026-08-25",
      detail: "演示会员 C 当前为暂停状态。页面按钮只模拟后台操作，不会撤销任何真实会话。",
    },
    {
      id: "MBR-004",
      label: "演示会员 D",
      tier: "观察版",
      status: "active",
      quota: "2 / 5 次",
      activity: "2026-08-22",
      detail: "演示会员 D 使用观察版额度查看了本地演示数据，未连接真实会员资料。",
    },
  ];

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function setNotice(text) {
    if (notice) notice.textContent = text;
  }

  function setMemberNotice(text) {
    if (memberNotice) memberNotice.textContent = text;
    setNotice(text);
  }

  function memberStatusLabel(status) {
    if (status === "paused") return "已暂停";
    if (status === "review") return "待确认";
    return "正常";
  }

  function memberStatusClass(status) {
    if (status === "paused") return "status-paused";
    if (status === "review") return "status-review";
    return "status-active";
  }

  function memberMatches(row) {
    const query = (memberSearch?.value || "").trim().toLowerCase();
    const status = memberStatusFilter?.value || "all";
    const searchable = `${row.label} ${row.id} ${row.tier}`.toLowerCase();
    return (!query || searchable.includes(query)) && (status === "all" || row.status === status);
  }

  function renderMembers() {
    if (!memberList) return;
    const visibleRows = memberRows.filter(memberMatches);
    if (!visibleRows.length) {
      memberList.innerHTML = '<tr><td colspan="6"><div class="admin-empty">没有符合条件的演示会员。</div></td></tr>';
      return;
    }
    memberList.innerHTML = visibleRows
      .map((row) => `
        <tr data-member-row data-member-id="${escapeHtml(row.id)}">
          <th scope="row">${escapeHtml(row.label)}<span>${escapeHtml(row.id)}</span></th>
          <td>${escapeHtml(row.tier)}</td>
          <td><span class="admin-table-status ${memberStatusClass(row.status)}">${memberStatusLabel(row.status)}</span></td>
          <td>${escapeHtml(row.quota)}</td>
          <td>${escapeHtml(row.activity)}</td>
          <td class="member-actions">
            <button class="admin-action" type="button" data-member-action="view" data-member-id="${escapeHtml(row.id)}">查看</button>
            <button class="admin-action" type="button" data-member-action="toggle" data-member-id="${escapeHtml(row.id)}">${row.status === "paused" ? "恢复（演示）" : "暂停（演示）"}</button>
          </td>
        </tr>
      `)
      .join("");
    memberList.querySelectorAll("[data-member-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const row = memberRows.find((item) => item.id === button.dataset.memberId);
        if (!row) return;
        if (button.dataset.memberAction === "view") {
          if (detail) detail.textContent = row.detail;
          setMemberNotice(`已查看 ${row.label} 的演示详情；真实会员字段仍需服务端授权。`);
          return;
        }
        row.status = row.status === "paused" ? "active" : "paused";
        setMemberNotice(`已在本地演示状态中${row.status === "paused" ? "暂停" : "恢复"} ${row.label}；没有修改真实会员资料。`);
        renderMembers();
      });
    });
  }

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
    const copy = element.dataset.detail || element.querySelector("p")?.textContent || element.querySelector("div span")?.textContent || "已选择本地演示记录。";
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
  memberSearch?.addEventListener("input", renderMembers);
  memberStatusFilter?.addEventListener("change", renderMembers);

  document.querySelectorAll("[data-admin-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const row = button.closest("[data-admin-row]");
      const item = row || button.closest("li") || button.closest(".admin-service-row");
      setDetailFrom(item);

      if (button.dataset.adminAction === "review") {
        updateRowStatus(row, "已完成", "status-complete", "已完成");
        setNotice("已在本地演示状态中标记为完成；真实审核仍需记录工作人员、时间和审计结果。" );
        return;
      }
      if (button.dataset.adminAction === "retry") {
        updateRowStatus(row, "运行中", "status-active", "运行中");
        setNotice("已在本地演示状态中进入重试；真实重试需要由可靠 worker 执行并记录失败分类。" );
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
        setNotice("服务任务已在本地演示状态中分配；真实派单需要校验角色、归属和审计记录。" );
        return;
      }
      setNotice("已查看本地演示详情；真实数据和敏感字段不会通过前端直接授权。" );
    });
  });

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

  const hashTab = window.location.hash.replace("#", "");
  applyTab(tabs.some((tab) => tab.dataset.adminTab === hashTab) ? hashTab : "overview");
  applyStatusFilter();
  renderMembers();
})();

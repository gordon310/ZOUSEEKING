(() => {
  // Presentation helpers for the admin page: demo fixture data, HTML row
  // builders for live /api/admin/* payloads, status/format label maps and the
  // shared pager markup. Pure string/DOM-free logic so admin.js stays a thin
  // controller (AGENTS frontend rule: no single growing controller file).
  //
  // Every server-provided value goes through escape() before it is placed into
  // HTML strings. Live data is never mixed into the demo fixtures.

  const t = (key, fallback = "") => {
    const i18n = window.ZouI18n;
    return i18n && typeof i18n.t === "function" ? i18n.t(key, fallback) : fallback;
  };

  function escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function shortId(value, length = 8) {
    const text = String(value ?? "");
    return text.length > length ? `${text.slice(0, length)}…` : text || "—";
  }

  function fmtDateTime(iso) {
    if (!iso) return "—";
    return String(iso).slice(0, 19).replace("T", " ");
  }

  // payment_orders.refunds store amount_minor. Convert using ISO 4217 minor
  // exponents for well-known currencies; anything unknown is shown as raw minor
  // units with an explicit suffix so the number is never silently scaled.
  const CURRENCY_EXPONENTS = {
    JPY: 0, KRW: 0, VND: 0, ISK: 0, CLP: 0,
    USD: 2, EUR: 2, CNY: 2, GBP: 2, HKD: 2, SGD: 2, AUD: 2, CAD: 2, CHF: 2,
    NZD: 2, SEK: 2, NOK: 2, DKK: 2, TWD: 2, THB: 2, MOP: 2, CZK: 2, PLN: 2,
  };

  function fmtMoney(currency, amountMinor) {
    if (amountMinor === null || amountMinor === undefined) return "—";
    const exponent = CURRENCY_EXPONENTS[currency] ?? 0;
    const amount = Number(amountMinor) / 10 ** exponent;
    const label = `${currency || ""} ${amount.toLocaleString("zh-CN", {
      minimumFractionDigits: exponent > 0 ? exponent : 0,
      maximumFractionDigits: Math.max(exponent, 0),
    })}`;
    return exponent === 0 && !(currency in CURRENCY_EXPONENTS) ? `${label} minor` : label;
  }

  const ORDER_STATUS_TEXT = {
    pending: "待支付",
    paid: "已支付",
    failed: "支付失败",
    canceled: "已取消",
    refunded: "已退款",
    partially_refunded: "部分退款",
  };
  const REFUND_STATUS_TEXT = {
    pending: "待处理",
    succeeded: "已退款",
    failed: "退款失败",
  };
  const MEMBER_TIER_TEXT = {
    free: "免费版",
    basic: "基础版",
    observer: "观察版",
    pro: "专业版",
    premium: "高级版",
  };

  function statusClassFor(status) {
    const map = {
      paid: "status-complete",
      succeeded: "status-complete",
      completed: "status-complete",
      active: "status-active",
      running: "status-active",
      pending: "status-review",
      review: "status-review",
      failed: "status-failed",
      paused: "status-paused",
      canceled: "status-paused",
      refunded: "status-paused",
      partially_refunded: "status-paused",
    };
    return map[status] || "";
  }

  function badge(status, text) {
    const cls = statusClassFor(status);
    return `<span class="admin-table-status ${cls}">${escape(text)}</span>`;
  }

  function statusLabel(status, fallback) {
    return fallback[status] || String(status || "—");
  }

  function emptyRow(colspan, message) {
    return `<tr><td colspan="${colspan}"><div class="admin-empty">${escape(message)}</div></td></tr>`;
  }

  function loadingRow(colspan) {
    return emptyRow(colspan, t("admin.loading", "正在从后台加载……"));
  }

  // ---------- demo fixtures (unchanged default surface) ----------

  const demoMembers = [
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

  function demoMemberStatusLabel(status) {
    if (status === "paused") return "已暂停";
    if (status === "review") return "待确认";
    return "正常";
  }

  function demoMemberStatusClass(status) {
    if (status === "paused") return "status-paused";
    if (status === "review") return "status-review";
    return "status-active";
  }

  function demoMemberRowsHtml(rows) {
    if (!rows.length) {
      return emptyRow(6, "没有符合条件的演示会员。");
    }
    return rows
      .map((row) => `
        <tr data-member-row data-member-id="${escape(row.id)}">
          <th scope="row">${escape(row.label)}<span>${escape(row.id)}</span></th>
          <td>${escape(row.tier)}</td>
          <td><span class="admin-table-status ${demoMemberStatusClass(row.status)}">${demoMemberStatusLabel(row.status)}</span></td>
          <td>${escape(row.quota)}</td>
          <td>${escape(row.activity)}</td>
          <td class="member-actions">
            <button class="admin-action" type="button" data-member-action="view" data-member-id="${escape(row.id)}">查看</button>
            <button class="admin-action" type="button" data-member-action="toggle" data-member-id="${escape(row.id)}">${row.status === "paused" ? "恢复（演示）" : "暂停（演示）"}</button>
          </td>
        </tr>
      `)
      .join("");
  }

  // ---------- live member list / detail ----------

  const memberLiveHeaders = `
    <tr>
      <th scope="col">会员</th><th scope="col">等级</th><th scope="col">内部角色</th>
      <th scope="col">订阅</th><th scope="col">当月用量</th><th scope="col">加入时间</th><th scope="col">操作</th>
    </tr>`;
  const memberDemoHeaders = `
    <tr>
      <th scope="col">会员</th><th scope="col">等级</th><th scope="col">状态</th><th scope="col">额度使用</th>
      <th scope="col">最近活动</th><th scope="col">操作</th>
    </tr>`;

  function tierLabel(tier) {
    return MEMBER_TIER_TEXT[tier] || tier || "—";
  }

  function rolesText(roles) {
    if (!Array.isArray(roles) || !roles.length) return "—";
    return roles.map((role) => (role && typeof role === "object" ? role.role : role) || "").filter(Boolean).join("、");
  }

  function subscriptionsText(subscriptions) {
    if (!Array.isArray(subscriptions) || !subscriptions.length) return "—";
    return subscriptions
      .map((sub) => {
        const code = sub?.product_code || "—";
        const st = sub?.status || "";
        return `${escape(code)}<span>${escape(statusLabel(st, ORDER_STATUS_TEXT))}</span>`;
      })
      .join("、");
  }

  function quotasText(quotas) {
    if (!Array.isArray(quotas) || !quotas.length) return "—";
    return quotas
      .map((quota) => {
        const kind = quota?.usage_kind || "query";
        const used = quota?.consumed_units ?? 0;
        const limit = quota?.limit_units ?? 0;
        return `${used} / ${limit}（${kind}）`;
      })
      .join("、");
  }

  function memberLiveRowsHtml(items, writePendingLabel) {
    if (!items || !items.length) {
      return emptyRow(7, t("admin.emptyMembers", "没有符合条件的会员。"));
    }
    return items
      .map((member) => {
        const name = member.display_name || member.username || shortId(member.user_id, 12);
        const sub = [member.email, shortId(member.user_id)].filter(Boolean).join(" · ");
        return `
        <tr data-member-row data-member-id="${escape(member.user_id)}">
          <th scope="row">${escape(name)}<span>${escape(sub)}</span></th>
          <td>${escape(tierLabel(member.membership_tier))}</td>
          <td>${escape(rolesText(member.roles))}</td>
          <td>${subscriptionsText(member.subscriptions)}</td>
          <td>${quotasText(member.usage_quotas)}</td>
          <td>${escape(fmtDateTime(member.created_at))}</td>
          <td class="member-actions">
            <button class="admin-action" type="button" data-member-action="view" data-member-id="${escape(member.user_id)}">查看</button>
            <button class="admin-action" type="button" disabled title="${escape(writePendingLabel)}">${escape(writePendingLabel)}</button>
          </td>
        </tr>`;
      })
      .join("");
  }

  function memberDetailText(member) {
    const lines = [];
    const name = member.display_name || member.username || "—";
    lines.push(`会员：${name}`);
    if (member.email) lines.push(`邮箱（按角色显示）：${member.email}`);
    lines.push(`等级：${tierLabel(member.membership_tier)}（每日额度 ${member.daily_query_limit ?? "—"} 次）`);
    lines.push(`加入时间：${fmtDateTime(member.created_at)}`);
    lines.push(`内部角色：${rolesText(member.roles)}`);
    const subs = Array.isArray(member.subscriptions) ? member.subscriptions : [];
    lines.push(`订阅：${subs.length ? subs.map((s) => `${s.product_code || "—"}（${s.status || "—"}）`).join("、") : "无"}`);
    const events = Array.isArray(member.usage_events) ? member.usage_events : [];
    if (events.length) {
      const recent = events
        .slice(0, 5)
        .map((event) => `${fmtDateTime(event.created_at)} ${event.usage_kind || ""} ${event.operation || ""}（+${event.units ?? 0}）`)
        .join("；");
      lines.push(`最近用量事件：${recent}`);
    }
    return lines.join("\n");
  }

  // ---------- live audit ----------

  function auditRowsHtml(items) {
    if (!items || !items.length) {
      return emptyRow(5, t("admin.emptyAudit", "没有符合条件的审计记录。"));
    }
    return items
      .map((item) => {
        let summary = "";
        if (item.summary === null || item.summary === undefined) {
          summary = "";
        } else if (typeof item.summary === "object") {
          summary = JSON.stringify(item.summary);
        } else {
          summary = String(item.summary);
        }
        const shown = summary.length > 200 ? `${summary.slice(0, 200)}…` : summary;
        const target = item.target_id ? `${item.target_type || ""} · ${shortId(item.target_id, 10)}` : (item.target_type || "—");
        return `
        <tr>
          <td>${escape(fmtDateTime(item.occurred_at))}</td>
          <td>${escape(shortId(item.actor_user_id))}</td>
          <td><code>${escape(item.action || "—")}</code></td>
          <td>${escape(target)}</td>
          <td class="admin-wrap" title="${escape(summary)}">${escape(shown || "—")}</td>
        </tr>`;
      })
      .join("");
  }

  // ---------- live finance ----------

  function orderRowsHtml(items) {
    if (!items || !items.length) {
      return emptyRow(7, t("admin.emptyOrders", "没有符合条件的订单。"));
    }
    return items
      .map((order) => `
        <tr>
          <th scope="row">${escape(order.order_no || shortId(order.id))}${order.organization_id ? `<span>组织 ${escape(shortId(order.organization_id))}</span>` : ""}</th>
          <td>${escape(order.product_code || "—")}</td>
          <td>${escape(shortId(order.owner_user_id))}</td>
          <td>${badge(order.status, statusLabel(order.status, ORDER_STATUS_TEXT))}</td>
          <td class="num">${escape(fmtMoney(order.currency, order.amount_minor))}</td>
          <td>${escape(fmtDateTime(order.paid_at))}</td>
          <td>${escape(fmtDateTime(order.created_at))}</td>
        </tr>`)
      .join("");
  }

  function refundRowsHtml(items) {
    if (!items || !items.length) {
      return emptyRow(6, t("admin.emptyRefunds", "没有符合条件的退款记录。"));
    }
    return items
      .map((refund) => `
        <tr>
          <th scope="row">${escape(refund.order_no || shortId(refund.order_id))}</th>
          <td class="num">${escape(fmtMoney(refund.currency, refund.amount_minor))}</td>
          <td>${badge(refund.status, statusLabel(refund.status, REFUND_STATUS_TEXT))}</td>
          <td>${escape(refund.reason || "—")}</td>
          <td>${escape(shortId(refund.provider_refund_id))}</td>
          <td>${escape(fmtDateTime(refund.created_at))}</td>
        </tr>`)
      .join("");
  }

  // ---------- pager ----------

  function totalPages(pageSize, total) {
    return Math.max(1, Math.ceil((Number(total) || 0) / (Number(pageSize) || 1)));
  }

  function pagerHtml({ page = 1, pageSize = 20, total = 0, target = "" } = {}) {
    const pages = totalPages(pageSize, total);
    const current = Math.min(Math.max(Number(page) || 1, 1), pages);
    return `
      <div class="admin-pager" data-pager-target="${escape(target)}">
        <button type="button" class="admin-action" data-pager-dir="prev" ${current <= 1 ? "disabled" : ""}>上一页</button>
        <span>第 ${current} / ${pages} 页 · 共 ${Number(total) || 0} 条</span>
        <button type="button" class="admin-action" data-pager-dir="next" ${current >= pages ? "disabled" : ""}>下一页</button>
      </div>`;
  }

  window.ZouAdminViews = Object.freeze({
    escape,
    shortId,
    fmtDateTime,
    fmtMoney,
    emptyRow,
    loadingRow,
    demoMembers,
    demoMemberRowsHtml,
    memberDemoHeaders,
    memberLiveHeaders,
    memberLiveRowsHtml,
    memberDetailText,
    auditRowsHtml,
    orderRowsHtml,
    refundRowsHtml,
    pagerHtml,
    totalPages,
    ORDER_STATUS_TEXT,
    REFUND_STATUS_TEXT,
  });
})();

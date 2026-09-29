import { getValidAccessToken, listMyQueries } from "./api-client.js?v=20260926-r67";

const DEMO_MODE = new URL(window.location.href).searchParams.get("demo") === "1";
const EMPTY_MODE = new URL(window.location.href).searchParams.get("empty") === "1";
const t = (key, fallback) => window.ZouI18n?.t(key, fallback) || fallback;
let currentProjects = [];

const PROJECTS = [
  { id: "project-01", title: "大阪市北区・塔楼演示项目", purpose: "自住购买", status: "preview", statusLabel: "资料检查", completion: 62, updated: "2026-08-27 11:05", note: "已确认售价、面积；法律与管理资料不足。" },
  { id: "project-02", title: "大阪市中央区・公寓演示项目", purpose: "投资出租", status: "running", statusLabel: "生成中", completion: 71, updated: "2026-08-26 18:40", note: "正在计算分析指标。" },
  { id: "project-03", title: "大阪市西区・塔楼演示项目", purpose: "自住购买", status: "completed", statusLabel: "完整报告", completion: 86, updated: "2026-08-24 09:12", note: "报告 V2 已生成，可补充资料更新一次。" },
  { id: "project-04", title: "大阪市淀川区・公寓演示项目", purpose: "投资出租", status: "failed", statusLabel: "生成失败", completion: 48, updated: "2026-08-22 16:20", note: "资料处理暂时不可用，可重试。" },
  { id: "project-05", title: "大阪市天王寺区・塔楼演示项目", purpose: "自住购买", status: "draft", statusLabel: "资料待确认", completion: 28, updated: "2026-08-20 13:30", note: "已上传资料，等待确认关键字段。" },
];

const elements = {
  banner: document.querySelector("#projectsReviewBanner"),
  filter: document.querySelector("#statusFilter"),
  list: document.querySelector("#projectList"),
  empty: document.querySelector("#projectsEmptyState"),
  count: document.querySelector("#projectCount"),
  description: document.querySelector("#projectListDescription"),
  notice: document.querySelector("#projectsNotice"),
  authState: document.querySelector("#projectsAuthState"),
  listShell: document.querySelector(".project-list-shell"),
  menuToggle: document.querySelector("#projectsMenuToggle"),
  menu: document.querySelector("#projectsMenu"),
};

function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function latestJob(project) {
  return Array.isArray(project?.generation_jobs) ? project.generation_jobs[0] || null : null;
}

function projectFromQuery(query) {
  const job = latestJob(query);
  const rawStatus = query?.status === "completed" || query?.status === "failed"
    ? query.status
    : job?.status || query?.status || "draft";
  const status = rawStatus === "completed"
    ? "completed"
    : rawStatus === "failed"
      ? "failed"
      : rawStatus === "running"
        ? "running"
        : "draft";
  const location = [query?.prefecture, query?.city, query?.ward].filter(Boolean).join("") || "未命名地区";
  const title = `${location}・${query?.asset_type || "物件"}`;
  const timestamp = job?.created_at || query?.updated_at || query?.created_at;
  const updated = timestamp
    ? new Date(timestamp).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
    : "—";
  const completion = status === "completed"
    ? 100
    : Math.max(0, Math.min(100, Number(job?.progress ?? query?.progress ?? 0)));
  const statusLabel = {
    completed: "完整报告",
    failed: "生成失败",
    running: "生成中",
    draft: "待处理",
  }[status];
  return {
    id: query?.id || query?.query_key || title,
    title,
    purpose: query?.year && query?.month ? `${query.year}年${query.month}月查询` : "物件分析项目",
    status,
    statusLabel,
    completion,
    updated,
    note: job?.error_message || job?.current_step || (status === "completed" ? "报告已生成，可查看结果。" : "项目已保存，等待下一步处理。"),
    reportKey: query?.query_key || "",
  };
}

function stateLink(project) {
  if (!project.reportKey || project.status !== "completed") return "";
  return `report.html?key=${encodeURIComponent(project.reportKey)}`;
}

function renderProjects(projects = currentProjects) {
  const filter = elements.filter?.value || "all";
  const source = DEMO_MODE ? PROJECTS : projects;
  const visible = EMPTY_MODE && DEMO_MODE ? [] : source.filter((project) => filter === "all" || project.status === filter);
  elements.count.textContent = `${visible.length} 个项目`;
  elements.description.textContent = filter === "all" ? "按最近更新排序" : `筛选：${visible.length} 个${elements.filter.selectedOptions[0].textContent}项目`;
  elements.empty.hidden = visible.length > 0;
  elements.list.hidden = visible.length === 0;
  elements.list.innerHTML = visible
    .map((project) => `
      <article class="project-list-item">
        <div>
          <h3>${escapeHtml(project.title)}</h3>
          <p>${escapeHtml(project.note)}</p>
          <small>最近更新 ${escapeHtml(project.updated)}</small>
        </div>
        <div class="project-status-cell">
          <span class="project-status project-status-${escapeHtml(project.status)}">${escapeHtml(project.statusLabel)}</span>
          <small>${project.status === "completed" ? "报告 V2" : project.status === "running" ? "当前任务进行中" : "需要下一步"}</small>
        </div>
        <div class="project-completeness">
          <div class="project-purpose">${escapeHtml(project.purpose)}</div>
          <div class="project-completeness-row"><span>资料完整度</span><strong>${project.completion}%</strong></div>
          <div class="project-list-meter" aria-hidden="true"><span style="width:${project.completion}%"></span></div>
        </div>
        ${stateLink(project) ? `<a href="${stateLink(project)}">查看报告</a>` : `<span class="project-link-muted">项目处理中</span>`}
      </article>
    `)
    .join("");
}

function showAuthState() {
  elements.authState.hidden = false;
  elements.listShell.hidden = true;
  elements.empty.hidden = true;
  elements.notice.textContent = "";
}

async function loadProjects() {
  if (DEMO_MODE) {
    elements.banner.hidden = false;
    if (EMPTY_MODE) elements.notice.textContent = t("projects.emptyDemoNotice", "当前是空状态演示；切换状态筛选不会填充真实项目。");
    currentProjects = PROJECTS;
    renderProjects();
    return;
  }

  elements.banner.hidden = true;
  elements.authState.hidden = true;
  elements.listShell.hidden = false;
  const accessToken = await getValidAccessToken();
  if (!accessToken) {
    showAuthState();
    return;
  }
  elements.notice.textContent = "正在读取你的项目……";
  try {
    const queries = await listMyQueries(accessToken);
    currentProjects = (Array.isArray(queries) ? queries : []).map(projectFromQuery);
    renderProjects();
    elements.notice.textContent = "";
  } catch (error) {
    if (error?.status === 401 || error?.status === 403) {
      showAuthState();
      return;
    }
    elements.notice.textContent = error?.message || "项目暂时无法读取，请稍后重试。";
    currentProjects = [];
    renderProjects([]);
  }
}

function initializeMenu() {
  elements.menuToggle.addEventListener("click", () => {
    const open = elements.menu.hidden;
    elements.menu.hidden = !open;
    elements.menuToggle.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.menu.hidden) {
      elements.menu.hidden = true;
      elements.menuToggle.setAttribute("aria-expanded", "false");
      elements.menuToggle.focus();
    }
  });
}

elements.filter.addEventListener("change", () => renderProjects());
initializeMenu();
loadProjects();

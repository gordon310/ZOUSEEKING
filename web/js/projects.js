const DEMO_MODE = new URL(window.location.href).searchParams.get("demo") === "1";
const EMPTY_MODE = new URL(window.location.href).searchParams.get("empty") === "1";

const PROJECTS = [
  { id: "project-01", title: "大阪市北区・塔楼演示项目", purpose: "自住购买", status: "preview", statusLabel: "免费预览", completion: 62, updated: "2026-08-27 11:05", note: "已确认售价、面积；法律与管理资料不足。" },
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
  menuToggle: document.querySelector("#projectsMenuToggle"),
  menu: document.querySelector("#projectsMenu"),
};

function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function stateLink(project) {
  const state = project.status === "draft" ? "preview" : project.status;
  return `project.html?demo=1&state=${encodeURIComponent(state)}`;
}

function renderProjects() {
  const filter = elements.filter?.value || "all";
  const visible = EMPTY_MODE ? [] : PROJECTS.filter((project) => filter === "all" || project.status === filter);
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
        <a href="${stateLink(project)}">查看项目</a>
      </article>
    `)
    .join("");
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

if (DEMO_MODE) elements.banner.hidden = false;
if (DEMO_MODE && EMPTY_MODE) elements.notice.textContent = "当前是空状态演示；切换状态筛选不会填充真实项目。";
elements.filter.addEventListener("change", renderProjects);
initializeMenu();
renderProjects();

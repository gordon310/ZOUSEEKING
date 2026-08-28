const DEMO_STATES = new Set(["preview", "ready", "running", "completed", "failed", "update"]);
const DEMO_QUERY = "demo";
const STATE_QUERY = "state";
const VERSION_QUERY = "version";
const VERSION_IDS = new Set(["v1", "v2", "v3"]);

const state = {
  demo: false,
  view: "preview",
  activeVersion: "v2",
};

const elements = {
  reviewToolbar: document.querySelector("#reviewToolbar"),
  stateSelector: document.querySelector("#stateSelector"),
  status: document.querySelector("#projectStatus"),
  notice: document.querySelector("#workspaceNotice"),
  reportState: document.querySelector("#reportState"),
  freeReportContent: document.querySelector("#freeReportContent"),
  reportContent: document.querySelector("#reportContent"),
  reportVersionLabel: document.querySelector("#reportVersionLabel"),
  reportMetaVersion: document.querySelector("#reportMetaVersion"),
  reportFooterVersion: document.querySelector("#reportFooterVersion"),
  versionList: document.querySelector("#versionList"),
  versionCount: document.querySelector("#versionCount"),
  completionValue: document.querySelector("#completionValue"),
  completionMeter: document.querySelector("#completionMeter"),
  nextTitle: document.querySelector("#nextActionTitle"),
  nextCopy: document.querySelector("#nextActionCopy"),
  nextButton: document.querySelector("#nextActionButton"),
  serviceRequestButton: document.querySelector("#serviceRequestButton"),
  serviceRequestStatus: document.querySelector("#serviceRequestStatus"),
  menuToggle: document.querySelector("#workspaceMenuToggle"),
  menu: document.querySelector("#workspaceMenu"),
};

const VERSION_DATA = [
  { id: "v2", label: "V2", title: "补充资料后的报告", date: "2026-08-27 14:20", note: "新增 2 项确认字段；仍有关键资料不足。" },
  { id: "v1", label: "V1", title: "首轮免费预览", date: "2026-08-27 11:05", note: "基于初始提交资料生成的免费预览。" },
];

const VERSION_3 = { id: "v3", label: "V3", title: "更新后的报告", date: "2026-08-27 15:10", note: "补充资料后的新版本；V2 保持只读。" };

const STATE_DATA = {
  preview: {
    status: "免费预览",
    completion: 62,
    nextTitle: "先注册保存项目",
    nextCopy: "匿名资料会在 24 小时后到期。注册后才能继续管理项目和报告版本。",
    nextLabel: "注册并保存项目",
    notice: "当前显示免费预览。它只反映资料完整度，不包含完整行动结论。",
  },
  ready: {
    status: "权益已准备",
    completion: 62,
    nextTitle: "可以启动完整分析",
    nextCopy: "内部测试权益已经准备。启动后系统会固定输入、数据和规则版本。",
    nextLabel: "启动完整分析",
    notice: "这是完整分析启动前的确认状态。权益和额度由受信任后端决定。",
  },
  running: {
    status: "生成中",
    completion: 62,
    nextTitle: "分析正在生成",
    nextCopy: "可以离开页面；回到项目工作台后继续查看进度。",
    nextLabel: "模拟生成完成",
    notice: "生成任务正在运行。实际产品应由后端任务状态驱动，而不是由浏览器自行判断完成。",
  },
  completed: {
    status: "完整报告",
    completion: 74,
    nextTitle: "补充资料后更新一次",
    nextCopy: "首轮完整报告生成后的 30 天内，可以补充资料并生成一次新版本。",
    nextLabel: "补充资料",
    notice: "当前显示完整报告演示。所有数字和结论均为 synthetic_fixture，不代表真实判断。",
  },
  failed: {
    status: "生成失败",
    completion: 62,
    nextTitle: "先检查资料，再重试",
    nextCopy: "本次任务没有覆盖或改写已有报告。修复临时问题后可以安全重试。",
    nextLabel: "重新生成",
    notice: "生成失败不会覆盖历史版本；错误详情应由后端记录失败类别。",
  },
  update: {
    status: "补充资料",
    completion: 68,
    nextTitle: "提交补充资料",
    nextCopy: "补充资料只会生成新版本，旧报告保持只读。",
    nextLabel: "提交并生成 V3",
    notice: "当前是一次性更新入口演示。真实上传仍需经过 FastAPI 授权和私有 Storage。",
  },
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function currentUrl() {
  return new URL(window.location.href);
}

function readState() {
  const url = currentUrl();
  state.demo = url.searchParams.get(DEMO_QUERY) === "1";
  const requested = url.searchParams.get(STATE_QUERY);
  state.view = DEMO_STATES.has(requested) ? requested : "preview";
  const requestedVersion = url.searchParams.get(VERSION_QUERY);
  state.activeVersion = VERSION_IDS.has(requestedVersion)
    ? requestedVersion
    : state.view === "completed" || state.view === "update" ? "v2" : "v1";
}

function writeState(nextView) {
  const url = currentUrl();
  const previousView = state.view;
  url.searchParams.set(STATE_QUERY, nextView);
  if (state.demo) url.searchParams.set(DEMO_QUERY, "1");
  state.view = nextView;
  if (nextView === "completed" && previousView !== "update") state.activeVersion = "v2";
  if (nextView === "update" && state.activeVersion === "v1") state.activeVersion = "v2";
  if (nextView !== "completed" && nextView !== "update") state.activeVersion = "v1";
  url.searchParams.set(VERSION_QUERY, state.activeVersion);
  history.replaceState(null, "", url);
  render();
}

function setNotice(message) {
  elements.notice.textContent = message;
}

function stateMark(view) {
  if (view === "completed") return { symbol: "✓", tone: "green" };
  if (view === "failed") return { symbol: "!", tone: "red" };
  if (view === "running") return { symbol: "↗", tone: "blue" };
  if (view === "update") return { symbol: "+", tone: "blue" };
  return { symbol: "i", tone: "" };
}

function renderStateCard(view) {
  const config = STATE_DATA[view];
  const mark = stateMark(view);
  const classes = ["state-card", view === "preview" ? "locked" : "", view].filter(Boolean).join(" ");

  if (view === "preview") {
    return `
      <article class="${classes}">
        <div class="state-header">
          <div>
            <p class="eyebrow">FREE PREVIEW</p>
            <h2>免费项目预览已生成</h2>
            <p>你已经看到资料完整度、费用项目和当前提醒。完整报告会固定本次输入和规则版本。</p>
          </div>
          <span class="state-mark">${mark.symbol}</span>
        </div>
        <div class="state-meta"><span>6 个完整度维度</span><span>3 项优先补充事项</span><span>可比数据：尚未检查</span></div>
        <div class="state-actions">
          <button class="primary-button" type="button" data-action="ready">注册并保存项目</button>
          <a class="outline-button" href="property-analysis.html">继续补充资料</a>
        </div>
      </article>
    `;
  }

  if (view === "ready") {
    return `
      <article class="${classes}">
        <div class="state-header">
          <div>
            <p class="eyebrow">ANALYSIS ACCESS</p>
            <h2>完整分析权益已准备</h2>
            <p>启动后会锁定资料版本、市场数据期间、税费规则和法规版本；生成过程中不能静默覆盖旧报告。</p>
          </div>
          <span class="state-mark green">${mark.symbol}</span>
        </div>
        <div class="state-meta"><span>内部测试权益 · 1 次</span><span>预计生成：演示</span><span>报告旧版本：保留</span></div>
        <div class="state-actions">
          <button class="primary-button" type="button" data-action="running">启动完整分析</button>
          <button class="outline-button" type="button" data-action="preview">返回免费预览</button>
        </div>
      </article>
    `;
  }

  if (view === "running") {
    return `
      <article class="${classes}">
        <div class="state-header">
          <div>
            <p class="eyebrow">REPORT GENERATION</p>
            <h2>完整报告正在生成</h2>
            <p>输入版本 I1 已固定。页面可以安全离开，稍后从“我的项目”回来查看。</p>
          </div>
          <span class="state-mark ${mark.tone}">${mark.symbol}</span>
        </div>
        <div class="progress-track" aria-label="报告生成进度"><span style="width: 58%"></span></div>
        <ol class="progress-steps">
          <li class="is-done">✓ 固定输入版本</li>
          <li class="is-done">✓ 整理证据</li>
          <li class="is-current">正在计算指标</li>
          <li>生成报告版本</li>
        </ol>
        <div class="state-meta"><span>当前阶段：计算分析指标</span><span>任务编号：演示任务</span></div>
        <div class="state-actions">
          <button class="primary-button" type="button" data-action="completed">模拟生成完成</button>
          <button class="outline-button" type="button" data-action="failed">模拟失败状态</button>
        </div>
      </article>
    `;
  }

  if (view === "failed") {
    return `
      <article class="${classes}">
        <div class="state-header">
          <div>
            <p class="eyebrow">REPORT GENERATION</p>
            <h2>这次没有生成成功</h2>
            <p>报告版本没有被覆盖。可以重试；如果问题持续，保留失败类别并联系支持。</p>
          </div>
          <span class="state-mark ${mark.tone}">${mark.symbol}</span>
        </div>
        <div class="upload-summary">
          <div><strong>失败类别：资料处理暂时不可用</strong><span>已有 V1 免费预览仍然可查看，输入资料不会丢失。</span></div>
          <span class="table-status missing">未生成 V2</span>
        </div>
        <div class="state-actions">
          <button class="primary-button" type="button" data-action="running">重新生成</button>
          <button class="outline-button" type="button" data-action="preview">查看免费预览</button>
        </div>
      </article>
    `;
  }

  if (view === "update") {
    return `
      <article class="${classes}">
        <div class="state-header">
          <div>
            <p class="eyebrow">REPORT UPDATE</p>
            <h2>补充资料，生成一次更新版本</h2>
            <p>上传管理规约、修缮计划或合同资料；系统会保留旧报告，并在新版本中标记发生了什么变化。</p>
          </div>
          <span class="state-mark ${mark.tone}">${mark.symbol}</span>
        </div>
        <div class="upload-summary">
          <div><strong>拖拽资料到这里，或选择文件</strong><span>PDF、JPG、PNG · 单个文件不超过 20 MiB · 演示不会上传真实文件</span></div>
          <button class="upload-button" type="button" data-action="fake-upload">选择演示文件</button>
        </div>
        <div class="state-actions">
          <button class="primary-button" type="button" data-action="completed">提交并生成 V3</button>
          <button class="outline-button" type="button" data-action="cancel-update">暂不更新</button>
        </div>
      </article>
    `;
  }

  const currentVersion = state.activeVersion.toUpperCase();

  return `
    <article class="${classes}">
      <div class="state-header">
        <div>
          <p class="eyebrow">FULL REPORT</p>
          <h2>完整报告已经生成</h2>
          <p>报告包含 11 个固定章节，展开行动结论、来源可信度、市场比较、成本情景、法律检查和下一步行动。</p>
        </div>
        <span class="state-mark ${mark.tone}">${mark.symbol}</span>
      </div>
      <div class="state-meta"><span>报告版本 ${currentVersion}</span><span>输入版本 I1</span><span>生成时间：2026-08-27 14:20</span></div>
      <div class="state-actions">
        <button class="primary-button" type="button" data-action="scroll-report">查看完整报告</button>
        <button class="outline-button" type="button" data-action="update">补充资料并更新一次</button>
      </div>
    </article>
  `;
}

function renderVersions(view) {
  const showV2 = view === "completed" || view === "update";
  const versions = showV2
    ? state.activeVersion === "v3" ? [VERSION_3, ...VERSION_DATA] : VERSION_DATA
    : [VERSION_DATA[1]];
  elements.versionCount.textContent = `${versions.length} 个版本`;
  elements.versionList.innerHTML = versions
    .map((version) => `
      <article class="version-item">
        <span class="version-number">${escapeHtml(version.label)}</span>
        <p><strong>${escapeHtml(version.title)}</strong><small>${escapeHtml(version.date)} · ${escapeHtml(version.note)}</small></p>
        <button type="button" data-version="${escapeHtml(version.id)}">${version.id === state.activeVersion ? "当前版本" : "查看版本"}</button>
      </article>
    `)
    .join("");

  elements.versionList.querySelectorAll("[data-version]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeVersion = button.dataset.version;
      const url = currentUrl();
      url.searchParams.set(VERSION_QUERY, state.activeVersion);
      history.replaceState(null, "", url);
      render();
      setNotice(`${state.activeVersion.toUpperCase()} 为只读历史版本。旧版本不会被新报告覆盖。`);
    });
  });
}

function updateNextAction(view) {
  const config = STATE_DATA[view];
  elements.nextTitle.textContent = config.nextTitle;
  elements.nextCopy.textContent = config.nextCopy;
  elements.nextButton.textContent = config.nextLabel;
  elements.nextButton.dataset.action = view === "preview" ? "ready" : view === "ready" ? "running" : view === "running" ? "completed" : view === "failed" ? "running" : view === "update" ? "completed" : "update";
}

function render() {
  const config = STATE_DATA[state.view];
  elements.reviewToolbar.hidden = !state.demo;
  elements.stateSelector.value = state.view;
  elements.status.textContent = config.status;
  elements.status.dataset.state = state.view;
  elements.notice.textContent = config.notice;
  elements.reportState.innerHTML = renderStateCard(state.view);
  const isReportView = state.view === "completed" || state.view === "update";
  const showFreePreview = state.view === "preview" || (isReportView && state.activeVersion === "v1");
  elements.freeReportContent.hidden = !showFreePreview;
  elements.reportContent.hidden = !(isReportView && state.activeVersion !== "v1");
  const reportVersion = state.activeVersion.toUpperCase();
  elements.reportVersionLabel.textContent = `FULL REPORT · ${reportVersion} · SYNTHETIC FIXTURE`;
  elements.reportMetaVersion.textContent = reportVersion;
  elements.reportFooterVersion.textContent = `收费完整版 ${reportVersion} · 输入版本 I1 · 数据类别 synthetic_fixture`;
  elements.completionValue.textContent = `${config.completion}%`;
  elements.completionMeter.style.width = `${config.completion}%`;
  updateNextAction(state.view);
  renderVersions(state.view);
  bindActions();
}

function bindActions() {
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => handleAction(button.dataset.action));
  });
}

function submitServiceRequest() {
  const selected = document.querySelector("input[name='serviceRequest']:checked");
  if (!selected) {
    setNotice("请先选择一种小象避坑服务；当前没有提交任何真实订单。" );
    return;
  }
  elements.serviceRequestButton.disabled = true;
  elements.serviceRequestButton.textContent = "需求已提交（演示）";
  elements.serviceRequestStatus.textContent = `已选择「${selected.value}」。真实版本会进入 B 端服务队列，当前只改变本地页面状态。`;
  setNotice("服务需求已在本地演示状态中提交；真实派单需要后端校验和审计记录。" );
}

function handleAction(action) {
  if (action === "ready") return writeState("ready");
  if (action === "running") return writeState("running");
  if (action === "completed") {
    state.activeVersion = state.view === "update" ? "v3" : "v2";
    writeState("completed");
    return;
  }
  if (action === "failed") return writeState("failed");
  if (action === "update") return writeState("update");
  if (action === "cancel-update") {
    state.activeVersion = "v2";
    return writeState("completed");
  }
  if (action === "preview") return writeState("preview");
  if (action === "fake-upload") {
    setNotice("已选择演示文件：长期修缮计划_演示.pdf。真实版本会在这里显示上传状态和文件大小。", "info");
    return;
  }
  if (action === "scroll-report") {
    const report = state.activeVersion === "v1" ? elements.freeReportContent : elements.reportContent;
    report.hidden = false;
    report.scrollIntoView({ behavior: "smooth", block: "start" });
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

readState();
initializeMenu();
elements.stateSelector.addEventListener("change", (event) => writeState(event.target.value));
elements.serviceRequestButton?.addEventListener("click", submitServiceRequest);
render();

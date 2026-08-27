import {
  addTextOrUrlInput,
  confirmField,
  convertSession,
  createSession,
  generatePreview,
  getExistingAccessToken,
  uploadFiles,
} from "./api-client.js";

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const INTAKE_SESSION_KEY = "zou_house_property_intake_session";
const DIMENSION_LABELS = {
  identity: "项目身份",
  price_cost: "价格与费用",
  yield: "收益测算",
  building_management: "建筑与管理资料",
  legal_transaction: "法律与交易资料",
  source_trust: "数据来源可信度",
};
const STATUS_LABELS = {
  complete: "已完成",
  partial: "部分完成",
  empty: "尚未填写",
  insufficient_data: "关键资料不足",
};

const state = {
  session: loadAnonymousSession(),
  stage: "submit",
  busy: false,
  preview: null,
};

const elements = {
  submitStep: document.querySelector("#submitStep"),
  confirmStep: document.querySelector("#confirmStep"),
  previewStep: document.querySelector("#previewStep"),
  submitForm: document.querySelector("#submitForm"),
  confirmForm: document.querySelector("#confirmForm"),
  source: document.querySelector("#propertySource"),
  files: document.querySelector("#propertyFiles"),
  submitButton: document.querySelector("#submitButton"),
  previewButton: document.querySelector("#previewButton"),
  saveButton: document.querySelector("#saveProjectButton"),
  status: document.querySelector("#intakeStatus"),
  sourceSummary: document.querySelector("#sourceSummary"),
  inputSummary: document.querySelector("#inputSummary"),
  previewContent: document.querySelector("#previewContent"),
  progressItems: Array.from(document.querySelectorAll("[data-stage]")),
};

function loadAnonymousSession() {
  try {
    const raw = window.sessionStorage.getItem(INTAKE_SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveAnonymousSession(session) {
  state.session = session;
  try {
    if (session) window.sessionStorage.setItem(INTAKE_SESSION_KEY, JSON.stringify(session));
    else window.sessionStorage.removeItem(INTAKE_SESSION_KEY);
  } catch {
    // The API still remains usable when browser storage is unavailable for this session.
  }
}

function setStatus(message, tone = "error") {
  elements.status.textContent = message;
  elements.status.dataset.tone = tone;
  elements.status.classList.toggle("is-empty", !message);
  if (message) {
    elements.status.focus();
  }
}

function setBusy(button, busy, busyLabel) {
  button.disabled = busy;
  if (busy) {
    button.dataset.defaultLabel = button.textContent;
    button.textContent = busyLabel;
  } else if (button.dataset.defaultLabel) {
    button.textContent = button.dataset.defaultLabel;
  }
}

function setStage(stage) {
  state.stage = stage;
  const sections = {
    submit: elements.submitStep,
    confirm: elements.confirmStep,
    preview: elements.previewStep,
  };
  const visibleStage = stage === "save" ? "preview" : stage;
  Object.entries(sections).forEach(([name, section]) => {
    section.hidden = name !== visibleStage;
  });
  const currentStep = { submit: 2, confirm: 3, preview: 4, save: 5 }[stage] || 2;
  elements.progressItems.forEach((item) => {
    const itemStep = Number(item.dataset.step || 0);
    const isCurrent = itemStep === currentStep;
    const isDone = itemStep < currentStep;
    item.classList.toggle("is-current", isCurrent);
    item.classList.toggle("is-done", isDone);
    if (isCurrent) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  });
}

function validateFiles(files) {
  for (const file of files) {
    const extension = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
    const allowed = {
      ".pdf": "application/pdf",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".png": "image/png",
    };
    if (!allowed[extension] || (file.type && file.type !== allowed[extension])) {
      return "仅支持 PDF、JPG、PNG 文件。";
    }
    if (!file.size) return "上传文件不能为空。";
    if (file.size > MAX_UPLOAD_BYTES) return "单个文件不能超过 20 MiB。";
  }
  return "";
}

function formValue(fieldName) {
  const input = document.querySelector(`[data-field='${fieldName}']`);
  if (!input) return null;
  const raw = input.value.trim();
  if (!raw) return null;
  return input.type === "number" ? Number(raw) : raw;
}

function createElement(tagName, text, className = "") {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderInputSummary() {
  elements.sourceSummary.textContent = elements.source.value.trim();
  elements.inputSummary.textContent = elements.files.files.length
    ? `${elements.files.files.length} 个文件已提交，等待自动提取。`
    : "文字资料已提交，等待自动提取。";
}

function renderDimension(dimensionName, result) {
  const item = createElement("div", undefined, "dimension-row");
  const heading = createElement("div", undefined, "dimension-heading");
  heading.append(
    createElement("strong", DIMENSION_LABELS[dimensionName] || dimensionName),
    createElement("span", STATUS_LABELS[result.status] || result.status, "dimension-status"),
  );
  const meter = document.createElement("meter");
  meter.min = 0;
  meter.max = 100;
  meter.value = Number(result.percent || 0);
  meter.setAttribute("aria-label", `${DIMENSION_LABELS[dimensionName] || dimensionName}完整度`);
  const summary = createElement(
    "p",
    `${result.confirmed}/${result.total} 项已确认 · ${result.percent}% · ${STATUS_LABELS[result.status] || result.status}`,
    "dimension-summary",
  );
  item.append(heading, meter, summary);
  if (Array.isArray(result.missing_critical) && result.missing_critical.length) {
    item.append(createElement("p", `关键资料不足：${result.missing_critical.join("、")}`, "dimension-warning"));
  }
  return item;
}

function renderPreview(preview) {
  elements.previewContent.replaceChildren();
  const completeness = createElement("section", undefined, "preview-section");
  completeness.append(createElement("h3", "资料完整度"));
  Object.entries(preview.completeness || {}).forEach(([name, result]) => {
    completeness.append(renderDimension(name, result));
  });

  const costs = createElement("section", undefined, "preview-section");
  costs.append(createElement("h3", "购入费用项目"));
  costs.append(
    createElement(
      "p",
      "本阶段只列出待核对项目，不计算税费金额；规则版本尚未加载。",
      "preview-note",
    ),
  );
  const costList = createElement("ul", undefined, "plain-list");
  (preview.acquisition_costs?.items || []).forEach((item) => costList.append(createElement("li", item)));
  costs.append(costList);

  const risks = createElement("section", undefined, "preview-section");
  risks.append(createElement("h3", "当前资料提醒"));
  const riskItems = preview.risk_summary?.items || [];
  risks.append(
    createElement(
      "p",
      riskItems.length ? `发现 ${riskItems.length} 项资料提醒，暂不代表法律结论。` : "暂未发现资料冲突。",
      "preview-note",
    ),
  );
  riskItems.forEach((risk) => {
    const fields = Array.isArray(risk.fields) ? `：${risk.fields.join("、")}` : "";
    risks.append(createElement("p", `${DIMENSION_LABELS[risk.dimension] || risk.dimension}${fields}`, "risk-item"));
  });

  const comparison = createElement("section", undefined, "preview-section preview-limitations");
  comparison.append(
    createElement("h3", "市场可比与下一步"),
    createElement("p", "市场可比数据：尚未检查。完整报告、税费金额、自动提取和法律判断将在后续阶段提供。"),
  );

  elements.previewContent.append(completeness, costs, risks, comparison);
}

async function startIntake(event) {
  event.preventDefault();
  if (state.busy) return;
  const purpose = document.querySelector("input[name='purpose']:checked")?.value;
  const source = elements.source.value.trim();
  const files = Array.from(elements.files.files || []);
  const fileError = validateFiles(files);
  if (!purpose) return setStatus("请选择自住或投资出租。", "error");
  if (!source && !files.length) return setStatus("请先填写房源链接或说明，或上传资料。", "error");
  if (fileError) return setStatus(fileError, "error");

  state.busy = true;
  setBusy(elements.submitButton, true, "正在整理…");
  setStatus("正在创建临时分析项目，资料会在 24 小时后到期。", "info");
  try {
    const session = await createSession(purpose);
    saveAnonymousSession({
      sessionId: session.session_id,
      rawToken: session.session_token,
      expiresAt: session.expires_at,
    });
    if (source) await addTextOrUrlInput(session.session_id, session.session_token, source);
    if (files.length) await uploadFiles(session.session_id, session.session_token, files);
    renderInputSummary();
    setStatus("资料已收好。第一版不会假装自动提取，先请你核对关键字段。", "success");
    setStage("confirm");
    document.querySelector("[data-field='asking_price_jpy']")?.focus();
  } catch (error) {
    setStatus(error.message || "资料提交失败，请稍后重试。", "error");
  } finally {
    state.busy = false;
    setBusy(elements.submitButton, false);
  }
}

async function createFreePreview(event) {
  event.preventDefault();
  if (state.busy) return;
  if (!state.session?.sessionId || !state.session?.rawToken) {
    setStatus("临时项目已失效，请重新开始。", "error");
    setStage("submit");
    return;
  }
  const fields = ["asking_price_jpy", "area_sqm", "building_name", "address", "land_right"]
    .map((fieldName) => ({ fieldName, value: formValue(fieldName) }))
    .filter((field) => field.value !== null);
  if (!fields.length) return setStatus("至少确认售价或专有面积中的一项，再生成预览。", "error");

  state.busy = true;
  setBusy(elements.previewButton, true, "正在生成…");
  setStatus("正在保存确认字段并计算资料完整度。", "info");
  try {
    for (const field of fields) {
      await confirmField(state.session.sessionId, state.session.rawToken, field.fieldName, field.value);
    }
    state.preview = await generatePreview(state.session.sessionId, state.session.rawToken);
    renderPreview(state.preview);
    setStage("preview");
    setStatus("免费预览已生成。它只反映当前资料完整度，不替代专业交易核查。", "success");
  } catch (error) {
    setStatus(error.message || "预览生成失败，请稍后重试。", "error");
  } finally {
    state.busy = false;
    setBusy(elements.previewButton, false);
  }
}

async function saveProject() {
  if (state.busy) return;
  const accessToken = getExistingAccessToken();
  if (!accessToken) {
    setStatus("请先在首页完成 Supabase 登录，再返回这里保存项目。匿名项目会保留到 24 小时到期。", "info");
    return;
  }
  state.busy = true;
  setBusy(elements.saveButton, true, "正在保存…");
  try {
    const result = await convertSession(state.session.sessionId, state.session.rawToken, accessToken);
    saveAnonymousSession(null);
    setStage("save");
    elements.saveButton.textContent = "项目已保存";
    elements.saveButton.disabled = true;
    setStatus(`项目已保存到你的账户（${result.property_id}）。`, "success");
  } catch (error) {
    setStatus(error.message || "项目保存失败，请先确认登录状态。", "error");
  } finally {
    state.busy = false;
    if (!elements.saveButton.disabled) setBusy(elements.saveButton, false);
  }
}

function initialize() {
  elements.submitForm.addEventListener("submit", startIntake);
  elements.confirmForm.addEventListener("submit", createFreePreview);
  elements.saveButton.addEventListener("click", saveProject);
  elements.status.classList.add("is-empty");
  elements.status.textContent = "";
  if (state.session?.sessionId && state.session?.rawToken) {
    setStage("confirm");
    setStatus("已恢复本次临时项目，请继续核对字段。", "info");
  } else {
    setStage("submit");
  }
}

initialize();

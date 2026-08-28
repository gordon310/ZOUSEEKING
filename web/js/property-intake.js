import {
  addTextOrUrlInput,
  confirmField,
  convertSession,
  createSession,
  generatePreview,
  getExistingAccessToken,
  saveLocation,
  uploadFiles,
} from "./api-client.js";

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const INTAKE_SESSION_KEY = "zou_house_property_intake_session";
const LOCATION_CONSENT_VERSION = "location-2026-08";
const DEMO_MODE = new URL(window.location.href).searchParams.get("demo") === "1";
const EMPTY_LOCATION = {
  addressCandidate: "",
  addressSource: "",
  addressPrecision: "",
};
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
const FIELD_META = [
  {
    key: "asking_price_jpy",
    check: "price",
    label: "售价（日元）",
    icon: "¥",
    format: (value) => Number(value).toLocaleString("ja-JP"),
  },
  {
    key: "area_sqm",
    check: "area",
    label: "专有面积（平方米）",
    icon: "㎡",
    format: (value) => String(value),
  },
];
const CONFIRM_FIELDS = [
  "asking_price_jpy",
  "area_sqm",
  "building_name",
  "address",
  "land_right",
];

const DEMO_SESSION = {
  sessionId: "demo-intake-session",
  rawToken: "demo-intake-token",
  expiresAt: "2099-12-31T00:00:00Z",
};

const DEMO_LOCATION = {
  address_candidate: "大阪府大阪市北区梅田",
  address_source: "synthetic_fixture",
  address_precision: "town",
};

const ASSET_TYPE_LABELS = {
  apartment: "公寓",
  tower: "塔楼",
  detached_house: "一户建",
  other: "其他物件",
};

const DEMO_PREVIEW = {
  data_class: "synthetic_fixture",
  completeness: {
    identity: { confirmed: 4, total: 5, percent: 80, status: "partial", missing_critical: ["建筑年份"] },
    price_cost: { confirmed: 2, total: 5, percent: 40, status: "partial", missing_critical: ["购入费用依据"] },
    yield: { confirmed: 0, total: 4, percent: 0, status: "insufficient_data", missing_critical: ["租金与出租状态"] },
    building_management: { confirmed: 1, total: 5, percent: 20, status: "insufficient_data", missing_critical: ["长期修缮计划"] },
    legal_transaction: { confirmed: 0, total: 5, percent: 0, status: "insufficient_data", missing_critical: ["登记簿与合同资料"] },
    source_trust: { confirmed: 1, total: 3, percent: 33, status: "partial", missing_critical: ["原始来源定位"] },
  },
  acquisition_costs: {
    items: ["中介手续费：待合同或费用说明确认", "不动产取得税：需要评估额与适用条件", "登记相关费用：需要登记资料和司法书士报价"],
  },
  risk_summary: {
    items: [
      { dimension: "building_management", fields: ["管理费、修缮积立金和长期修缮计划"] },
      { dimension: "legal_transaction", fields: ["登记簿、重要事项说明书和合同草案"] },
      { dimension: "source_trust", fields: ["原始物件来源和取得时间"] },
    ],
  },
};

const state = {
  session: loadAnonymousSession(),
  assetType: "",
  location: { ...EMPTY_LOCATION },
  stage: "submit",
  busy: false,
  preview: null,
  projectNameTouched: false,
};
state.assetType = state.session?.assetType || "";
state.location = { ...EMPTY_LOCATION, ...(state.session?.location || {}) };

const elements = {
  submitStep: document.querySelector("#submitStep"),
  confirmStep: document.querySelector("#confirmStep"),
  previewStep: document.querySelector("#previewStep"),
  submitForm: document.querySelector("#submitForm"),
  confirmForm: document.querySelector("#confirmForm"),
  assetType: document.querySelector("#assetType"),
  source: document.querySelector("#propertySource"),
  files: document.querySelector("#propertyFiles"),
  photos: document.querySelector("#propertyPhotos"),
  takePhotoButton: document.querySelector("#takePhotoButton"),
  photoSelectionSummary: document.querySelector("#photoSelectionSummary"),
  submitButton: document.querySelector("#submitButton"),
  previewButton: document.querySelector("#previewButton"),
  saveButton: document.querySelector("#saveProjectButton"),
  savedProjectLink: document.querySelector("#savedProjectLink"),
  status: document.querySelector("#intakeStatus"),
  sourceSummary: document.querySelector("#sourceSummary"),
  assetTypeSummary: document.querySelector("#assetTypeSummary"),
  inputSummary: document.querySelector("#inputSummary"),
  locationButton: document.querySelector("#locationButton"),
  locationStatus: document.querySelector("#locationStatus"),
  locationCandidate: document.querySelector("#locationCandidate"),
  projectName: document.querySelector("#projectName"),
  projectNameHelp: document.querySelector("#projectNameHelp"),
  previewContent: document.querySelector("#previewContent"),
  progressItems: Array.from(document.querySelectorAll("[data-stage]")),
  characterCount: document.querySelector("#sourceCharacterCount"),
  progressRing: document.querySelector("#progressRing"),
  progressPercent: document.querySelector("#completionPercent"),
  completionCount: document.querySelector("#completion-count"),
  completionChecklist: document.querySelector("#completionChecklist"),
  purposeSummary: document.querySelector("#purposeSummary"),
  sourceSummaryRail: document.querySelector("#sourceSummaryRail"),
  recognizedFields: document.querySelector("#recognizedFields"),
  confirmedFieldCount: document.querySelector("#confirmedFieldCount"),
  confirmedFieldPercent: document.querySelector("#confirmedFieldPercent"),
  confirmedFieldBar: document.querySelector("#confirmedFieldBar"),
  railPreviewButton: document.querySelector("#railPreviewButton"),
  fileDropzone: document.querySelector(".file-dropzone"),
  menuToggle: document.querySelector("#menuToggle"),
  menu: document.querySelector("#beaconMenu"),
};

function loadAnonymousSession() {
  if (DEMO_MODE) return null;
  try {
    const raw = window.sessionStorage.getItem(INTAKE_SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveAnonymousSession(session) {
  state.session = session;
  if (DEMO_MODE) return;
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
  const currentStep = { submit: 1, confirm: 3, preview: 4, save: 5 }[stage] || 1;
  elements.progressItems.forEach((item) => {
    const itemStep = Number(item.dataset.step || 0);
    const isCurrent = itemStep === currentStep;
    const isDone = itemStep < currentStep;
    item.classList.toggle("is-current", isCurrent);
    item.classList.toggle("is-done", isDone);
    if (isCurrent) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  });
  updateProgressRail();
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

function validatePhotoFiles(files) {
  for (const file of files) {
    const extension = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
    const allowed = {
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".png": "image/png",
    };
    if (!allowed[extension] || (file.type && file.type !== allowed[extension])) {
      return "物件照片仅支持 JPG、PNG 文件。";
    }
    if (!file.size) return "物件照片不能为空。";
    if (file.size > MAX_UPLOAD_BYTES) return "单张物件照片不能超过 20 MiB。";
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

function updateSourceCount() {
  elements.characterCount.textContent = `${elements.source.value.length}/500`;
}

function updateFilePresentation() {
  const count = elements.files.files.length;
  const title = elements.fileDropzone.querySelector("strong");
  title.textContent = count ? `${count} 个文件已选择，可继续提交` : "点击上传或拖拽文件到此处";
}

function updatePhotoPresentation() {
  const count = elements.photos.files.length;
  elements.photoSelectionSummary.textContent = count ? `${count} 张物件照片已选择` : "尚未选择照片";
  updateLocationAvailability();
}

function handleFileDrop(event) {
  event.preventDefault();
  elements.fileDropzone.classList.remove("is-dragover");
  const droppedFiles = Array.from(event.dataTransfer?.files || []);
  if (!droppedFiles.length || typeof DataTransfer === "undefined") return;
  const transfer = new DataTransfer();
  droppedFiles.forEach((file) => transfer.items.add(file));
  elements.files.files = transfer.files;
  elements.files.dispatchEvent(new Event("change", { bubbles: true }));
}

function renderRecognizedFields() {
  elements.recognizedFields.replaceChildren();
  const filledFields = FIELD_META.filter(({ key }) => formValue(key) !== null);
  if (!filledFields.length) {
    elements.recognizedFields.append(createElement("p", "填写售价或面积后，会在这里显示。", "rail-empty"));
    return;
  }

  filledFields.forEach(({ key, label, icon, format }) => {
    const row = createElement("div", undefined, "recognized-field");
    row.append(
      createElement("span", icon, "recognized-field-icon"),
      createElement("span", label, "recognized-field-label"),
      createElement("strong", format(formValue(key)), "recognized-field-value"),
    );
    elements.recognizedFields.append(row);
  });
}

function updateProgressRail() {
  const purpose = document.querySelector("input[name='purpose']:checked")?.value;
  const assetType = elements.assetType.value;
  const source = elements.source.value.trim();
  const fileCount = elements.files.files.length;
  const photoCount = elements.photos.files.length;
  const checks = {
    purpose: Boolean(purpose),
    assetType: Boolean(assetType),
    source: Boolean(source || fileCount || photoCount),
    price: formValue("asking_price_jpy") !== null,
    area: formValue("area_sqm") !== null,
    files: fileCount > 0 || photoCount > 0,
  };
  const completed = Object.values(checks).filter(Boolean).length;
  const percent = Math.round((completed / Object.keys(checks).length) * 100);

  elements.completionCount.textContent = `已完成 ${completed}/6 项`;
  elements.progressPercent.textContent = `${percent}%`;
  elements.progressRing.style.setProperty("--progress", `${percent}%`);
  elements.progressRing.setAttribute("aria-label", `资料完整度 ${percent}%`);
  elements.completionChecklist.querySelectorAll("[data-check]").forEach((item) => {
    item.classList.toggle("is-complete", Boolean(checks[item.dataset.check]));
  });

  elements.purposeSummary.textContent =
    purpose === "rental_investment" ? "投资出租" : purpose === "self_use" ? "自住购买" : "未选择用途";
  const sourceSummary = source ||
    (fileCount || photoCount
      ? `${fileCount ? `${fileCount} 个资料文件` : ""}${fileCount && photoCount ? "、" : ""}${photoCount ? `${photoCount} 张物件照片` : ""}`
      : "尚未提交资料");
  elements.sourceSummaryRail.textContent = sourceSummary.length > 44 ? `${sourceSummary.slice(0, 44)}…` : sourceSummary;

  renderRecognizedFields();
  const confirmedCount = CONFIRM_FIELDS.filter((fieldName) => formValue(fieldName) !== null).length;
  const confirmedPercent = Math.round((confirmedCount / CONFIRM_FIELDS.length) * 100);
  elements.confirmedFieldCount.textContent = `${confirmedCount}/${CONFIRM_FIELDS.length} 项`;
  elements.confirmedFieldPercent.textContent = `${confirmedPercent}%`;
  elements.confirmedFieldBar.style.width = `${confirmedPercent}%`;
  elements.railPreviewButton.disabled = confirmedCount === 0;
  updateLocationAvailability();
}

function createElement(tagName, text, className = "") {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function saveLocationSummary(location) {
  state.location = { ...EMPTY_LOCATION, ...location };
  if (!DEMO_MODE && state.session) {
    saveAnonymousSession({
      ...state.session,
      location: {
        addressCandidate: state.location.addressCandidate,
        addressSource: state.location.addressSource,
        addressPrecision: state.location.addressPrecision,
      },
    });
  }
  elements.locationCandidate.textContent = state.location.addressCandidate || "尚未获取";
}

function updateLocationAvailability() {
  if (!elements.locationButton) return;
  const hasPhoto = elements.photos.files.length > 0;
  const hasSession = Boolean(state.session?.sessionId && state.session?.rawToken);
  elements.locationButton.disabled = state.busy || !hasPhoto || !hasSession;
  if (!hasPhoto) {
    elements.locationStatus.textContent = "拍摄照片后，可以在这里请求位置权限。";
  } else if (!hasSession) {
    elements.locationStatus.textContent = "先提交照片创建临时项目，再请求位置权限。";
  }
}

function locationErrorMessage(error) {
  if (error?.code === 1) return "无法获取设备位置（你拒绝了定位权限），请手工填写地址。";
  if (error?.code === 3) return "无法获取设备位置（请求超时），请手工填写地址。";
  return "无法获取设备位置，请手工填写地址。";
}

function requestDevicePosition() {
  if (!navigator.geolocation) {
    return Promise.reject(new Error("无法获取设备位置，请手工填写地址。"));
  }
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      maximumAge: 0,
      timeout: 10000,
    });
  });
}

function addressEvidenceLocator() {
  return state.location.addressSource === "gsi_reverse_geocoder"
    ? "国土地理院反向地址建议（用户确认/修正）"
    : "";
}

async function captureLocation() {
  if (state.busy) return;
  if (!state.session?.sessionId || !state.session?.rawToken) {
    setStatus("请先提交照片，创建临时分析项目。", "error");
    return;
  }
  if (!elements.photos.files.length) {
    setLocationStatus("请先拍摄或选择物件照片。", "error");
    return;
  }

  state.busy = true;
  setBusy(elements.locationButton, true, "正在获取位置…");
  setLocationStatus("正在请求设备位置权限…", "info");
  try {
    const position = await requestDevicePosition();
    const latitude = Number(position.coords?.latitude);
    const longitude = Number(position.coords?.longitude);
    const accuracy = Number(position.coords?.accuracy);
    if (![latitude, longitude, accuracy].every(Number.isFinite) || accuracy <= 0) {
      throw new Error("无法获取设备位置，请手工填写地址。");
    }
    const payload = {
      latitude,
      longitude,
      accuracy_m: accuracy,
      captured_at: new Date(position.timestamp || Date.now()).toISOString(),
      consent_version: LOCATION_CONSENT_VERSION,
      source: "device_geolocation",
    };
    const result = DEMO_MODE
      ? DEMO_LOCATION
      : await saveLocation(state.session.sessionId, state.session.rawToken, payload);
    saveLocationSummary({
      addressCandidate: result.address_candidate || "",
      addressSource: result.address_source || "unavailable",
      addressPrecision: result.address_precision || "",
    });
    const addressInput = document.querySelector("[data-field='address']");
    if (result.address_candidate && !addressInput.value.trim()) {
      addressInput.value = result.address_candidate;
      updateProgressRail();
    }
    if (result.address_candidate) {
      setLocationStatus("已生成地址建议，请在“完整地址”中确认或补全。", "success");
      setStatus("已生成地址建议，请确认后再生成免费预览。", "success");
    } else {
      setLocationStatus("位置已保存，但暂时没有地址建议，请手工填写地址。", "info");
      setStatus("位置已保存，但暂时没有地址建议，请手工填写地址。", "info");
    }
  } catch (error) {
    const message = error?.status ? "地址建议服务暂时不可用，请手工填写地址。" : locationErrorMessage(error);
    setLocationStatus(message, "error");
    setStatus(message, "info");
  } finally {
    state.busy = false;
    setBusy(elements.locationButton, false);
    updateLocationAvailability();
  }
}

function setLocationStatus(message, tone = "info") {
  elements.locationStatus.textContent = message;
  elements.locationStatus.dataset.tone = tone;
}

function updateProjectNameDefault() {
  if (state.projectNameTouched) return;
  elements.projectName.value = formValue("address") || "";
  elements.projectName.removeAttribute("aria-invalid");
}

function handleProjectNameError(error) {
  const messages = {
    duplicate_address: "同一地址已有调查记录，请手工修改记录名称。",
    project_name_taken: "这个调查记录名称已存在，请换一个名称。",
    project_name_required: "请先确认地址，或手工填写调查记录名称。",
  };
  const message = messages[error.code];
  if (!message) return false;
  elements.projectNameHelp.textContent = message;
  elements.projectName.setAttribute("aria-invalid", "true");
  setStatus(message, error.code === "project_name_required" ? "info" : "error");
  elements.projectName.focus();
  return true;
}

function renderInputSummary() {
  const assetType = elements.assetType.value;
  const source = elements.source.value.trim();
  const fileCount = elements.files.files.length;
  const photoCount = elements.photos.files.length;
  const submittedCount = fileCount + photoCount;
  elements.sourceSummary.textContent = source || "未提供文字说明";
  elements.assetTypeSummary.textContent = ASSET_TYPE_LABELS[assetType] || "未选择";
  elements.inputSummary.textContent = submittedCount
    ? `${fileCount ? `${fileCount} 个资料文件` : ""}${fileCount && photoCount ? "、" : ""}${photoCount ? `${photoCount} 张物件照片` : ""}已提交，等待人工确认。`
    : "文字资料已提交，等待自动提取。";
  updateProgressRail();
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
  completeness.append(createElement("p", `物件类型：${ASSET_TYPE_LABELS[state.assetType] || "未选择"}`, "preview-note"));
  if (preview.data_class === "synthetic_fixture") {
    completeness.append(createElement("p", "界面演示资料类别：synthetic_fixture。以下状态只用于确认操作流程，不代表真实结论。", "preview-note"));
  }
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
  const assetType = elements.assetType.value;
  const source = elements.source.value.trim();
  const files = Array.from(elements.files.files || []);
  const photos = Array.from(elements.photos.files || []);
  const fileError = validateFiles(files);
  const photoError = validatePhotoFiles(photos);
  if (!purpose) return setStatus("请选择自住或投资出租。", "error");
  if (!assetType) {
    elements.assetType.setAttribute("aria-invalid", "true");
    elements.assetType.focus();
    return setStatus("请选择物件类型（公寓、塔楼、一户建等），否则无法判断。", "error");
  }
  elements.assetType.removeAttribute("aria-invalid");
  state.assetType = assetType;
  if (!source && !files.length && !photos.length) return setStatus("请先填写物件链接或说明，或上传资料/物件照片。", "error");
  if (fileError) return setStatus(fileError, "error");
  if (photoError) return setStatus(photoError, "error");

  state.busy = true;
  setBusy(elements.submitButton, true, "正在整理…");
  setStatus("正在创建临时分析项目，资料会在 24 小时后到期。", "info");
  try {
    if (DEMO_MODE) {
      saveAnonymousSession({ ...DEMO_SESSION, assetType });
    } else {
      const session = await createSession(purpose);
      saveAnonymousSession({
        sessionId: session.session_id,
        rawToken: session.session_token,
        expiresAt: session.expires_at,
        assetType,
      });
      if (source) await addTextOrUrlInput(session.session_id, session.session_token, source);
      if (files.length || photos.length) {
        await uploadFiles(session.session_id, session.session_token, [...files, ...photos]);
      }
    }
    state.location = { ...EMPTY_LOCATION };
    elements.locationCandidate.textContent = "尚未获取";
    renderInputSummary();
    setStatus(
      DEMO_MODE
        ? "演示资料已收好。下一步请确认关键字段。"
        : "资料已收好。你可以请求照片位置生成地址建议，再核对关键字段。",
      "success",
    );
    setStage("confirm");
    updateLocationAvailability();
    document.querySelector("[data-field='asking_price_jpy']")?.focus();
  } catch (error) {
    setStatus(error.message || "资料提交失败，请稍后重试。", "error");
  } finally {
    state.busy = false;
    setBusy(elements.submitButton, false);
    updateLocationAvailability();
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
  setBusy(elements.railPreviewButton, true, "正在生成…");
  setStatus("正在保存确认字段并计算资料完整度。", "info");
  try {
    if (DEMO_MODE) {
      state.preview = DEMO_PREVIEW;
      renderPreview(state.preview);
      updateProjectNameDefault();
      setStage("preview");
      setStatus("演示预览已生成。当前内容只用于确认界面和流程。", "success");
      return;
    }
    for (const field of fields) {
      await confirmField(
        state.session.sessionId,
        state.session.rawToken,
        field.fieldName,
        field.value,
        "confirmed",
        field.fieldName === "address" ? { locator: addressEvidenceLocator() } : {},
      );
    }
    state.preview = await generatePreview(state.session.sessionId, state.session.rawToken);
    renderPreview(state.preview);
    updateProjectNameDefault();
    setStage("preview");
    setStatus("免费预览已生成。它只反映当前资料完整度，不替代专业交易核查。", "success");
  } catch (error) {
    setStatus(error.message || "预览生成失败，请稍后重试。", "error");
  } finally {
    state.busy = false;
    setBusy(elements.previewButton, false);
    setBusy(elements.railPreviewButton, false);
  }
}

async function saveProject() {
  if (state.busy) return;
  if (DEMO_MODE) {
    state.busy = true;
    setBusy(elements.saveButton, true, "保存演示项目…");
    saveAnonymousSession(null);
    setStage("save");
    elements.saveButton.textContent = "演示项目已保存";
    elements.saveButton.disabled = true;
    elements.savedProjectLink?.classList.remove("hidden");
    setStatus("演示项目已进入工作台界面。真实版本会在登录后由后端绑定项目归属。", "success");
    state.busy = false;
    return;
  }
  const accessToken = getExistingAccessToken();
  if (!accessToken) {
    setStatus("请先在首页完成 Supabase 登录，再返回这里保存项目。匿名项目会保留到 24 小时到期。", "info");
    return;
  }
  state.busy = true;
  setBusy(elements.saveButton, true, "正在保存…");
  try {
    const result = await convertSession(
      state.session.sessionId,
      state.session.rawToken,
      accessToken,
      elements.projectName.value,
    );
    saveAnonymousSession(null);
    setStage("save");
    elements.saveButton.textContent = "项目已保存";
    elements.saveButton.disabled = true;
    if (elements.savedProjectLink) {
      elements.savedProjectLink.classList.remove("hidden");
      elements.savedProjectLink.href = "project.html?demo=1&state=ready";
    }
    setStatus(`项目已保存到你的账户（${result.property_id}）。`, "success");
  } catch (error) {
    if (!handleProjectNameError(error)) {
      setStatus(error.message || "项目保存失败，请先确认登录状态。", "error");
    }
  } finally {
    state.busy = false;
    if (state.stage !== "save") setBusy(elements.saveButton, false);
  }
}

function closeMenu() {
  elements.menu.hidden = true;
  elements.menuToggle.setAttribute("aria-expanded", "false");
  elements.menuToggle.setAttribute("aria-label", "打开菜单");
}

function toggleMenu() {
  const willOpen = elements.menu.hidden;
  elements.menu.hidden = !willOpen;
  elements.menuToggle.setAttribute("aria-expanded", String(willOpen));
  elements.menuToggle.setAttribute("aria-label", willOpen ? "关闭菜单" : "打开菜单");
  if (willOpen) elements.menu.querySelector("a")?.focus();
}

function initialize() {
  elements.submitForm.addEventListener("submit", startIntake);
  elements.confirmForm.addEventListener("submit", createFreePreview);
  elements.saveButton.addEventListener("click", saveProject);
  elements.takePhotoButton.addEventListener("click", () => elements.photos.click());
  elements.source.addEventListener("input", () => {
    updateSourceCount();
    updateProgressRail();
  });
  elements.assetType.addEventListener("change", () => {
    state.assetType = elements.assetType.value;
    elements.assetType.removeAttribute("aria-invalid");
    updateProgressRail();
  });
  elements.files.addEventListener("change", () => {
    updateFilePresentation();
    updateProgressRail();
  });
  elements.photos.addEventListener("change", () => {
    updatePhotoPresentation();
    updateProgressRail();
  });
  elements.locationButton.addEventListener("click", captureLocation);
  elements.fileDropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    elements.fileDropzone.classList.add("is-dragover");
  });
  elements.fileDropzone.addEventListener("dragleave", () => {
    elements.fileDropzone.classList.remove("is-dragover");
  });
  elements.fileDropzone.addEventListener("drop", handleFileDrop);
  document.querySelectorAll("input[name='purpose']").forEach((input) => {
    input.addEventListener("change", updateProgressRail);
  });
  document.querySelectorAll("[data-field]").forEach((input) => {
    input.addEventListener("input", updateProgressRail);
  });
  elements.projectName.addEventListener("input", () => {
    state.projectNameTouched = true;
    elements.projectName.removeAttribute("aria-invalid");
    elements.projectNameHelp.textContent = "保存时会使用这个名称；同一用户下名称不能重复。";
  });
  elements.railPreviewButton.addEventListener("click", () => {
    if (!elements.railPreviewButton.disabled) elements.confirmForm.requestSubmit();
  });
  elements.menuToggle.addEventListener("click", toggleMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.menu.hidden) {
      closeMenu();
      elements.menuToggle.focus();
    }
  });
  elements.status.classList.add("is-empty");
  elements.status.textContent = "";
  if (DEMO_MODE) {
    document.querySelector("#demoBanner")?.removeAttribute("hidden");
    document.querySelector("#reviewLink")?.removeAttribute("hidden");
    setStatus("界面演示已开启：可以依次体验提交、确认、预览和保存。", "info");
  }
  updateSourceCount();
  updateFilePresentation();
  updatePhotoPresentation();
  elements.locationCandidate.textContent = state.location.addressCandidate || "尚未获取";
  elements.assetType.value = state.assetType;
  elements.assetTypeSummary.textContent = ASSET_TYPE_LABELS[state.assetType] || "未选择";
  updateProgressRail();
  if (state.session?.sessionId && state.session?.rawToken && state.assetType) {
    setStage("confirm");
    setStatus("已恢复本次临时项目，请继续核对字段。", "info");
  } else {
    setStage("submit");
    if (state.session?.sessionId && state.session?.rawToken) {
      setStatus("当前临时项目缺少物件类型，请重新选择后提交。", "info");
    }
  }
}

initialize();

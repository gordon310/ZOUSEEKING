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
const DEMO_MODE = new URL(window.location.href).searchParams.get("demo") === "1";
const t = (key, fallback) => window.ZouI18n?.t(key, fallback) || fallback;
const copy = (key, fallback, values = {}) => Object.entries(values).reduce(
  (text, [name, value]) => text.replaceAll(`{${name}}`, String(value ?? "")),
  t(key, fallback),
);
const NOT_SUBDIVIDED_VALUE = "__not_subdivided__";
const DIMENSION_LABELS = {
  identity: "intake.previewDimensionIdentity",
  price_cost: "intake.previewDimensionPriceCost",
  yield: "intake.previewDimensionYield",
  building_management: "intake.previewDimensionBuildingManagement",
  legal_transaction: "intake.previewDimensionLegalTransaction",
  source_trust: "intake.previewDimensionSourceTrust",
};
const STATUS_LABELS = {
  complete: "intake.previewStatusComplete",
  partial: "intake.previewStatusPartial",
  empty: "intake.previewStatusEmpty",
  insufficient_data: "intake.previewStatusInsufficientData",
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

const ASSET_TYPE_LABELS = {
  apartment: "intake.previewAssetTypeApartment",
  tower: "intake.previewAssetTypeTower",
  detached_house: "intake.previewAssetTypeDetachedHouse",
  other: "intake.previewAssetTypeOther",
};

function previewLabel(keyOrFallback, fallback = "") {
  return keyOrFallback?.startsWith("intake.") ? t(keyOrFallback, fallback) : keyOrFallback || fallback;
}

function previewValue(value) {
  if (value && typeof value === "object" && value.i18nKey) return t(value.i18nKey, value.fallback || "");
  return window.ZouI18n?.previewText?.(value) || String(value ?? "");
}

const DEMO_PREVIEW = {
  data_class: "synthetic_fixture",
  completeness: {
    identity: { confirmed: 4, total: 5, percent: 80, status: "partial", missing_critical: [{ i18nKey: "intake.previewDemoBuildingYear" }] },
    price_cost: { confirmed: 2, total: 5, percent: 40, status: "partial", missing_critical: [{ i18nKey: "intake.previewDemoAcquisitionBasis" }] },
    yield: { confirmed: 0, total: 4, percent: 0, status: "insufficient_data", missing_critical: [{ i18nKey: "intake.previewDemoRentStatus" }] },
    building_management: { confirmed: 1, total: 5, percent: 20, status: "insufficient_data", missing_critical: [{ i18nKey: "intake.previewDemoRepairPlan" }] },
    legal_transaction: { confirmed: 0, total: 5, percent: 0, status: "insufficient_data", missing_critical: [{ i18nKey: "intake.previewDemoRegistryContract" }] },
    source_trust: { confirmed: 1, total: 3, percent: 33, status: "partial", missing_critical: [{ i18nKey: "intake.previewDemoSourceLocation" }] },
  },
  acquisition_costs: {
    items: [
      { i18nKey: "intake.previewDemoBrokerage" },
      { i18nKey: "intake.previewDemoAcquisitionTax" },
      { i18nKey: "intake.previewDemoRegistration" },
    ],
  },
  risk_summary: {
    items: [
      { dimension: "building_management", fields: [{ i18nKey: "intake.previewDemoManagementFields" }] },
      { dimension: "legal_transaction", fields: [{ i18nKey: "intake.previewDemoLegalFields" }] },
      { dimension: "source_trust", fields: [{ i18nKey: "intake.previewDemoSourceFields" }] },
    ],
  },
};

const state = {
  session: loadAnonymousSession(),
  assetType: "",
  stage: "submit",
  busy: false,
  preview: null,
  projectNameTouched: false,
};
state.assetType = state.session?.assetType || "";

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
  locationStatus: document.querySelector("#locationStatus"),
  locationCandidate: document.querySelector("#locationCandidate"),
  projectName: document.querySelector("#projectName"),
  projectNameHelp: document.querySelector("#projectNameHelp"),
  previewContent: document.querySelector("#previewContent"),
  reportLink: document.querySelector("#reportLink"),
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
  prefecture: document.querySelector("#prefecture"),
  city: document.querySelector("#city"),
  ward: document.querySelector("#ward"),
  fileDropzone: document.querySelector(".file-dropzone"),
  menuToggle: document.querySelector("#menuToggle"),
  menu: document.querySelector("#beaconMenu"),
};

const fieldOptions = { prefectures: [], cities: {}, wards: {} };
let applyingLocationPrefill = false;

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
  if (!elements.status) return;
  elements.status.textContent = message;
  elements.status.dataset.tone = tone;
  elements.status.classList.toggle("is-empty", !message);
  if (message) {
    elements.status.focus?.();
  }
}

function setBusy(button, busy, busyLabel) {
  if (!button) return;
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
    if (section) section.hidden = name !== visibleStage;
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
      return t("intake.fileTypeInvalid", "仅支持 PDF、JPG、PNG 文件。");
    }
    if (!file.size) return t("intake.fileEmpty", "上传文件不能为空。");
    if (file.size > MAX_UPLOAD_BYTES) return t("intake.fileTooLarge", "单个文件不能超过 20 MiB。");
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
      return t("intake.photoTypeInvalid", "物件照片仅支持 JPG、PNG 文件。");
    }
    if (!file.size) return t("intake.photoEmpty", "物件照片不能为空。");
    if (file.size > MAX_UPLOAD_BYTES) return t("intake.photoTooLarge", "单张物件照片不能超过 20 MiB。");
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
  if (elements.characterCount && elements.source) elements.characterCount.textContent = `${elements.source.value.length}/500`;
}

function updateFilePresentation() {
  if (!elements.files || !elements.fileDropzone) return;
  const count = elements.files.files.length;
  const title = elements.fileDropzone.querySelector("strong");
  if (title) title.textContent = count ? copy("intake.filesSelected", "{count} 个文件已选择，可继续提交", { count }) : t("intake.fileDropTitle", "点击上传或拖拽文件到此处");
}

function updatePhotoPresentation() {
  if (!elements.photos) return;
  const count = elements.photos.files.length;
  if (elements.photoSelectionSummary) elements.photoSelectionSummary.textContent = count ? copy("intake.photosSelected", "{count} 张物件照片已选择", { count }) : t("intake.noPhotoSelected", "尚未选择照片");
}

function handleFileDrop(event) {
  event.preventDefault();
  if (!elements.fileDropzone || !elements.files) return;
  elements.fileDropzone.classList.remove("is-dragover");
  const droppedFiles = Array.from(event.dataTransfer?.files || []);
  if (!droppedFiles.length || typeof DataTransfer === "undefined") return;
  const transfer = new DataTransfer();
  droppedFiles.forEach((file) => transfer.items.add(file));
  elements.files.files = transfer.files;
  elements.files.dispatchEvent(new Event("change", { bubbles: true }));
}

function renderRecognizedFields() {
  if (!elements.recognizedFields) return;
  elements.recognizedFields.replaceChildren();
  const filledFields = FIELD_META.filter(({ key }) => formValue(key) !== null);
  if (!filledFields.length) {
    elements.recognizedFields.append(createElement("p", t("intake.recognizedEmptyRuntime", "填写售价或面积后，会在这里显示。"), "rail-empty"));
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
  if (!elements.assetType || !elements.source || !elements.files || !elements.photos) return;
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

  if (elements.completionCount) elements.completionCount.textContent = copy("intake.completedCountRuntime", "已完成 {completed}/6 项", { completed });
  if (elements.progressPercent) elements.progressPercent.textContent = `${percent}%`;
  elements.progressRing?.style.setProperty("--progress", `${percent}%`);
  elements.progressRing?.setAttribute("aria-label", `资料完整度 ${percent}%`);
  elements.completionChecklist?.querySelectorAll("[data-check]").forEach((item) => {
    item.classList.toggle("is-complete", Boolean(checks[item.dataset.check]));
  });

  if (elements.purposeSummary) elements.purposeSummary.textContent =
    purpose === "rental_investment" ? t("intake.rentalInvestment", "投资出租") : purpose === "self_use" ? t("intake.selfUse", "自住购买") : t("intake.purposeUnselected", "未选择用途");
  const sourceSummary = source ||
    (fileCount || photoCount
      ? `${fileCount ? `${fileCount} 个资料文件` : ""}${fileCount && photoCount ? "、" : ""}${photoCount ? `${photoCount} 张物件照片` : ""}`
      : t("intake.materialsUnsubmitted", "尚未提交资料"));
  if (elements.sourceSummaryRail) elements.sourceSummaryRail.textContent = sourceSummary.length > 44 ? `${sourceSummary.slice(0, 44)}…` : sourceSummary;

  renderRecognizedFields();
  const confirmedCount = CONFIRM_FIELDS.filter((fieldName) => formValue(fieldName) !== null).length;
  const confirmedPercent = Math.round((confirmedCount / CONFIRM_FIELDS.length) * 100);
  if (elements.confirmedFieldCount) elements.confirmedFieldCount.textContent = `${confirmedCount}/${CONFIRM_FIELDS.length} 项`;
  if (elements.confirmedFieldPercent) elements.confirmedFieldPercent.textContent = `${confirmedPercent}%`;
  if (elements.confirmedFieldBar) elements.confirmedFieldBar.style.width = `${confirmedPercent}%`;
}

function createElement(tagName, text, className = "") {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function setLocationStatus(message, tone = "info") {
  if (!elements.locationStatus) return;
  elements.locationStatus.textContent = message;
  elements.locationStatus.dataset.tone = tone;
}

function selectOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function resetLocationSelect(select, placeholder, options = []) {
  if (!select) return;
  select.replaceChildren(selectOption("", placeholder), ...options.map((value) => selectOption(value, value)));
  select.value = "";
  select.disabled = true;
}

function populateCities(prefecture, selected = "") {
  const cities = fieldOptions.cities[prefecture] || [];
  resetLocationSelect(elements.city, t("intake.selectCity", "请先选择市"), cities);
  if (!elements.city) return false;
  elements.city.disabled = cities.length === 0;
  if (!cities.includes(selected)) return false;
  elements.city.value = selected;
  return true;
}

function populateWards(prefecture, city, selected = "") {
  const wards = fieldOptions.wards[`${prefecture}::${city}`] || [];
  const options = wards.length ? wards : [NOT_SUBDIVIDED_VALUE];
  if (!elements.ward) return false;
  elements.ward.replaceChildren(
    selectOption("", t("intake.selectWard", "请先选择区")),
    ...options.map((value) => selectOption(value, value === NOT_SUBDIVIDED_VALUE ? t("intake.wardNotSubdivided", "未细分") : value)),
  );
  elements.ward.value = selected && options.includes(selected) ? selected : "";
  elements.ward.disabled = false;
  return Boolean(elements.ward.value);
}

function applyLocationPrefill(location = {}) {
  if (!elements.prefecture || !fieldOptions.prefectures.length) return;
  applyingLocationPrefill = true;
  try {
  const prefecture = String(location.prefecture || "");
  const city = String(location.city || "");
  const ward = String(location.ward || "");
  const canSetPrefecture = !elements.prefecture.dataset.userModified;
  const canSetCity = !elements.city?.dataset.userModified;
  const canSetWard = !elements.ward?.dataset.userModified;
  let matched = 0;
  if (canSetPrefecture && fieldOptions.prefectures.includes(prefecture)) {
    elements.prefecture.value = prefecture;
    matched += 1;
  }
  if (canSetPrefecture && elements.prefecture.value && canSetCity && populateCities(elements.prefecture.value, city)) {
    matched += 1;
  }
  if (canSetPrefecture && canSetCity && elements.city?.value && canSetWard && populateWards(elements.prefecture.value, elements.city.value, ward)) {
    matched += 1;
  }
  if (matched) {
    const complete = matched === 3;
    setLocationStatus(
      complete
        ? t("intake.locationPrefillComplete", "已根据照片位置自动填入都道府县、市和区，请核对。")
        : t("intake.locationPrefillPartial", "照片位置已填入可匹配的层级，请手动补全剩余地址层级。"),
      complete ? "success" : "info",
    );
  } else if (prefecture || city || ward) {
    setLocationStatus(t("intake.locationPrefillPartial", "照片位置已填入可匹配的层级，请手动补全剩余地址层级。"), "info");
  }
  } finally {
    applyingLocationPrefill = false;
  }
}

function locationValues() {
  return {
    prefecture: elements.prefecture?.value || "",
    city: elements.city?.value || "",
    ward: elements.ward?.value || "",
  };
}

function validateLocationFields() {
  const values = locationValues();
  if (!values.prefecture) return t("intake.prefectureRequired", "请选择都道府县。");
  if (!values.city) return t("intake.cityRequired", "请选择市。");
  if (!values.ward) return t("intake.wardRequired", "请选择区；没有区级资料时请选择「未细分」。");
  return "";
}

async function loadLocationFields() {
  try {
    const response = await fetch("field-options.json", { cache: "no-store" });
    if (!response.ok) throw new Error("field_options_unavailable");
    const payload = await response.json();
    fieldOptions.prefectures = Array.isArray(payload.prefectures) ? payload.prefectures : [];
    fieldOptions.cities = payload.cities || {};
    fieldOptions.wards = payload.wards || {};
  } catch {
    setStatus(t("intake.locationOptionsFailed", "地址选项暂时无法加载，请刷新后重试。"), "error");
    return;
  }
  if (elements.prefecture) {
    resetLocationSelect(elements.prefecture, t("intake.selectPrefecture", "请选择都道府县"), fieldOptions.prefectures);
    elements.prefecture.disabled = false;
  }
  let savedPrefill = null;
  try {
    savedPrefill = JSON.parse(window.sessionStorage.getItem("zou_recognition_prefill") || "null");
  } catch {
    savedPrefill = null;
  }
  if (savedPrefill) applyLocationPrefill(savedPrefill);
}

function updateProjectNameDefault() {
  if (state.projectNameTouched) return;
  if (elements.projectName) {
    elements.projectName.value = formValue("address") || "";
    elements.projectName.removeAttribute("aria-invalid");
  }
}

function handleProjectNameError(error) {
  const messages = {
    duplicate_address: t("intake.projectNameDuplicateAddress", "同一地址已有调查记录，请手工修改记录名称。"),
    project_name_taken: t("intake.projectNameTaken", "这个调查记录名称已存在，请换一个名称。"),
    project_name_required: t("intake.projectNameRequired", "请先确认地址，或手工填写调查记录名称。"),
  };
  const message = messages[error.code];
  if (!message) return false;
  if (elements.projectNameHelp) elements.projectNameHelp.textContent = message;
  elements.projectName?.setAttribute("aria-invalid", "true");
  setStatus(message, error.code === "project_name_required" ? "info" : "error");
  elements.projectName?.focus();
  return true;
}

function renderInputSummary() {
  if (!elements.assetType || !elements.source || !elements.files || !elements.photos) return;
  const assetType = elements.assetType.value;
  const source = elements.source.value.trim();
  const fileCount = elements.files.files.length;
  const photoCount = elements.photos.files.length;
  const submittedCount = fileCount + photoCount;
  if (elements.sourceSummary) elements.sourceSummary.textContent = source || "未提供文字说明";
  if (elements.assetTypeSummary) elements.assetTypeSummary.textContent = previewLabel(ASSET_TYPE_LABELS[assetType], t("intake.notSelected", "未选择"));
  if (elements.inputSummary) elements.inputSummary.textContent = submittedCount
    ? `${fileCount ? `${fileCount} 个资料文件` : ""}${fileCount && photoCount ? "、" : ""}${photoCount ? `${photoCount} 张物件照片` : ""}已提交，等待人工确认。`
    : "文字资料已提交，等待自动提取。";
  updateProgressRail();
}

function renderDimension(dimensionName, result) {
  const item = createElement("div", undefined, "dimension-row");
  const heading = createElement("div", undefined, "dimension-heading");
  const dimensionLabel = previewLabel(DIMENSION_LABELS[dimensionName], dimensionName);
  const statusLabel = previewLabel(STATUS_LABELS[result.status], result.status);
  heading.append(
    createElement("strong", dimensionLabel),
    createElement("span", statusLabel, "dimension-status"),
  );
  const meter = document.createElement("meter");
  meter.min = 0;
  meter.max = 100;
  meter.value = Number(result.percent || 0);
  meter.setAttribute("aria-label", copy("intake.previewMeterLabel", "{label}完整度", { label: dimensionLabel }));
  const summary = createElement(
    "p",
    copy("intake.previewDimensionSummary", "{confirmed}/{total} 项已确认 · {percent}% · {status}", {
      confirmed: result.confirmed,
      total: result.total,
      percent: result.percent,
      status: statusLabel,
    }),
    "dimension-summary",
  );
  item.append(heading, meter, summary);
  if (Array.isArray(result.missing_critical) && result.missing_critical.length) {
    item.append(createElement(
      "p",
      copy("intake.previewMissingCritical", "关键资料不足：{fields}", { fields: result.missing_critical.map(previewValue).join("、") }),
      "dimension-warning",
    ));
  }
  return item;
}

function renderPreview(preview) {
  if (!elements.previewContent) return;
  elements.previewContent.replaceChildren();
  const completeness = createElement("section", undefined, "preview-section");
  completeness.append(createElement("h3", t("intake.previewCompleteness", "资料完整度")));
  completeness.append(createElement(
    "p",
    copy("intake.previewAssetType", "物件类型：{assetType}", {
      assetType: previewLabel(ASSET_TYPE_LABELS[state.assetType], t("intake.notSelected", "未选择")),
    }),
    "preview-note",
  ));
  if (preview.data_class === "synthetic_fixture") {
    completeness.append(createElement("p", t("intake.demoFixtureNote", "界面演示资料类别：synthetic_fixture。以下状态只用于确认操作流程，不代表真实结论。"), "preview-note"));
  }
  Object.entries(preview.completeness || {}).forEach(([name, result]) => {
    completeness.append(renderDimension(name, result));
  });

  const costs = createElement("section", undefined, "preview-section");
  costs.append(createElement("h3", t("intake.acquisitionCosts", "购入费用项目")));
  const costData = preview.acquisition_costs || {};
  const costNote =
    costData.status === "insufficient_input"
      ? t("intake.previewCostNoteInsufficientInput", "缺少挂牌价/成交价，金额项暂无法估算；补充后可给出法定上限估算。")
      : costData.estimated_total_jpy
        ? t("intake.previewCostNoteEstimated", "以下为按法定上限/官定表的确定性估算；标注待补充的项需要评估额、贷款或物件信息。")
        : t("intake.previewCostNotePending", "本阶段只列出待核对项目，不计算税费金额。");
  costs.append(createElement("p", costNote, "preview-note"));
  const costList = createElement("ul", undefined, "plain-list");
  (costData.items || []).forEach((item) => {
    if (typeof item === "string" || item?.i18nKey) {
      costList.append(createElement("li", previewValue(item)));
      return;
    }
    const amount = item.estimated_jpy
      ? copy("intake.previewEstimatedAmount", "约 {amount}万日元", { amount: Math.round(item.estimated_jpy / 10000) })
      : t("intake.previewPendingInput", "待补充输入");
    const statusText = item.status === "estimated" ? "" : item.status === "needs_input" ? t("intake.previewNeedsInput", "（需补充）") : "";
    costList.append(createElement("li", `${previewValue(item.item)}：${amount}${statusText}`));
  });
  costs.append(costList);
  if (costData.estimated_total_jpy) {
    costs.append(
      createElement(
        "p",
        copy("intake.previewEstimatedTotal", "已估项合计：约 {amount}万日元（不含待补充项；参考估价非报价）", { amount: Math.round(costData.estimated_total_jpy / 10000) }),
        "preview-total",
      ),
    );
  }

  const risks = createElement("section", undefined, "preview-section");
  risks.append(createElement("h3", t("intake.currentRisks", "当前资料提醒")));
  const riskItems = preview.risk_summary?.items || [];
  risks.append(
    createElement(
      "p",
      riskItems.length
        ? copy("intake.previewRiskSummary", "发现 {count} 项资料提醒，暂不代表法律结论。", { count: riskItems.length })
        : t("intake.previewNoRisk", "暂未发现资料冲突。"),
      "preview-note",
    ),
  );
  riskItems.forEach((risk) => {
    if (typeof risk === "string") {
      risks.append(createElement("p", previewValue(risk), "risk-item"));
      return;
    }
    const dimension = previewLabel(DIMENSION_LABELS[risk.dimension], risk.dimension);
    const fields = Array.isArray(risk.fields) ? risk.fields.map(previewValue).join("、") : "";
    risks.append(createElement(
      "p",
      copy("intake.previewRiskItem", "{dimension}：{fields}", { dimension, fields }),
      "risk-item",
    ));
  });

  const comparison = createElement("section", undefined, "preview-section preview-limitations");
  comparison.append(createElement("h3", t("intake.marketComparison", "市场可比与下一步")));
  const comparable = preview.comparable || {};
  if (preview.comparable_status === "sufficient" && Array.isArray(comparable.reference) && comparable.reference.length) {
    const refList = createElement("ul", undefined, "plain-list");
    comparable.reference.forEach((row) => {
      const yen = row.amount_yen
        ? copy("intake.previewComparableAmount", "约 {amount}万日元", { amount: Math.round(row.amount_yen / 10000) })
        : row.amount_jpy || "";
      refList.append(createElement("li", copy("intake.previewComparableRow", "{layout}：{amount}（{period}）", {
        layout: row.layout || "",
        amount: yen,
        period: row.period || t("intake.previewPeriodUnknown", "期间未标注"),
      })));
    });
    comparison.append(createElement("p", t("intake.comparableReference", "同区中古マンション成交参考（国交省取引数据，出所明記）。"), "preview-note"), refList);
  } else if (preview.comparable_status === "insufficient") {
    comparison.append(createElement("p", t("intake.previewComparableInsufficient", "该地址所在区暂无覆盖（覆盖：东京23区/大阪市23区/横滨市18区）。"), "preview-note"));
  } else {
    comparison.append(createElement("p", t("intake.comparableUnavailable", "市场可比数据：尚未检查。完整报告、税费金额、自动提取和法律判断将在后续阶段提供。")));
  }

  elements.previewContent.append(completeness, costs, risks, comparison);
  const reportKey = preview?.query_key || state.session?.query_key || state.session?.queryKey || "";
  if (elements.reportLink && reportKey) {
    elements.reportLink.href = `report.html?key=${encodeURIComponent(reportKey)}`;
    elements.reportLink.classList.remove("hidden");
  }
}

async function startIntake(event) {
  event.preventDefault();
  if (state.busy) return;
  if (!elements.assetType || !elements.source || !elements.files || !elements.photos) {
    return setStatus(t("intake.formUnavailable", "表单暂时无法使用，请刷新后重试。"), "error");
  }
  const purpose = document.querySelector("input[name='purpose']:checked")?.value;
  const assetType = elements.assetType.value;
  const source = elements.source.value.trim();
  const files = Array.from(elements.files.files || []);
  const photos = Array.from(elements.photos.files || []);
  const fileError = validateFiles(files);
  const photoError = validatePhotoFiles(photos);
  if (!purpose) return setStatus(t("intake.purposeRequired", "请选择自住或投资出租。"), "error");
  if (!assetType) {
    elements.assetType.setAttribute("aria-invalid", "true");
    elements.assetType.focus();
    return setStatus(t("intake.assetTypeRequired", "请选择物件类型（公寓、塔楼、一户建等），否则无法判断。"), "error");
  }
  elements.assetType.removeAttribute("aria-invalid");
  state.assetType = assetType;
  if (!source && !files.length && !photos.length) return setStatus(t("intake.sourceRequired", "请先填写物件链接或说明，或上传资料/物件照片。"), "error");
  if (fileError) return setStatus(fileError, "error");
  if (photoError) return setStatus(photoError, "error");

  state.busy = true;
  setBusy(elements.submitButton, true, t("intake.organizing", "正在整理…"));
  setStatus(t("intake.sessionCreating", "正在创建临时分析项目，资料会在 24 小时后到期。"), "info");
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
    if (elements.locationCandidate) elements.locationCandidate.textContent = t("intake.notObtained", "尚未获取");
    renderInputSummary();
    setStatus(
      DEMO_MODE
        ? t("intake.demoMaterialsSubmitted", "演示资料已收好。下一步请确认关键字段。")
        : t("intake.materialsSubmittedStatus", "资料已收好。请核对自动填入的地址层级，或手动补全。"),
      "success",
    );
    setStage("confirm");
    document.querySelector("[data-field='asking_price_jpy']")?.focus();
  } catch (error) {
    setStatus(error.message || t("intake.materialSubmitFailed", "资料提交失败，请稍后重试。"), "error");
  } finally {
    state.busy = false;
    setBusy(elements.submitButton, false);
  }
}

async function createFreePreview(event) {
  event.preventDefault();
  if (state.busy) return;
  if (!state.session?.sessionId || !state.session?.rawToken) {
    setStatus(t("intake.sessionExpired", "临时项目已失效，请重新开始。"), "error");
    setStage("submit");
    return;
  }
  const locationError = validateLocationFields();
  if (locationError) {
    setStatus(locationError, "error");
    const firstMissing = [elements.prefecture, elements.city, elements.ward].find((select) => select && !select.value);
    firstMissing?.focus();
    return;
  }
  const addressInput = document.querySelector("[data-field='address']");
  if (addressInput && !addressInput.value.trim()) {
    const values = locationValues();
    addressInput.value = [values.prefecture, values.city, values.ward === NOT_SUBDIVIDED_VALUE ? "" : values.ward].filter(Boolean).join("");
    updateProgressRail();
  }
  const fields = ["asking_price_jpy", "area_sqm", "building_name", "address", "land_right"]
    .map((fieldName) => ({ fieldName, value: formValue(fieldName) }))
    .filter((field) => field.value !== null);
  if (!fields.length) return setStatus(t("intake.confirmFieldRequired", "至少确认售价或专有面积中的一项，再生成预览。"), "error");

  state.busy = true;
  setBusy(elements.previewButton, true, t("intake.generating", "正在生成…"));
  setStatus(t("intake.savingFields", "正在保存确认字段并计算资料完整度。"), "info");
  try {
    if (DEMO_MODE) {
      state.preview = DEMO_PREVIEW;
      renderPreview(state.preview);
      updateProjectNameDefault();
      setStage("preview");
      setStatus(t("intake.demoPreviewGenerated", "演示预览已生成。当前内容只用于确认界面和流程。"), "success");
      return;
    }
    for (const field of fields) {
      await confirmField(
        state.session.sessionId,
        state.session.rawToken,
        field.fieldName,
        field.value,
        "confirmed",
        {},
      );
    }
    state.preview = await generatePreview(state.session.sessionId, state.session.rawToken);
    renderPreview(state.preview);
    updateProjectNameDefault();
    setStage("preview");
    setStatus(t("intake.previewGenerated", "免费预览已生成。它只反映当前资料完整度，不替代专业交易核查。"), "success");
  } catch (error) {
    setStatus(error.message || t("intake.previewFailed", "预览生成失败，请稍后重试。"), "error");
  } finally {
    state.busy = false;
    setBusy(elements.previewButton, false);
  }
}

async function saveProject() {
  if (state.busy) return;
  if (!elements.saveButton) return setStatus(t("intake.formUnavailable", "表单暂时无法使用，请刷新后重试。"), "error");
  if (DEMO_MODE) {
    state.busy = true;
    setBusy(elements.saveButton, true, t("intake.demoProjectSaving", "保存演示项目…"));
    saveAnonymousSession(null);
    setStage("save");
    elements.saveButton.textContent = t("intake.demoProjectSaved", "演示项目已保存");
    elements.saveButton.disabled = true;
    elements.savedProjectLink?.classList.remove("hidden");
    setStatus(t("intake.demoProjectSavedStatus", "演示项目已进入工作台界面。真实版本会在登录后由后端绑定项目归属。"), "success");
    state.busy = false;
    return;
  }
  const accessToken = getExistingAccessToken();
  if (!accessToken) {
    setStatus(t("intake.loginRequiredToSave", "请先在首页完成 Supabase 登录，再返回这里保存项目。匿名项目会保留到 24 小时到期。"), "info");
    return;
  }
  state.busy = true;
  setBusy(elements.saveButton, true, t("intake.saving", "正在保存…"));
  try {
    const result = await convertSession(
      state.session.sessionId,
      state.session.rawToken,
      accessToken,
      elements.projectName?.value || "",
    );
    saveAnonymousSession(null);
    setStage("save");
    if (elements.saveButton) {
      elements.saveButton.textContent = t("intake.projectSaved", "项目已保存");
      elements.saveButton.disabled = true;
    }
    if (elements.savedProjectLink) {
      elements.savedProjectLink.classList.remove("hidden");
      elements.savedProjectLink.href = "project.html?demo=1&state=ready";
    }
    setStatus(copy("intake.projectSavedStatus", "项目已保存到你的账户（{propertyId}）。", { propertyId: result.property_id }), "success");
  } catch (error) {
    if (!handleProjectNameError(error)) {
      setStatus(error.message || t("intake.projectSaveFailed", "项目保存失败，请先确认登录状态。"), "error");
    }
  } finally {
    state.busy = false;
    if (state.stage !== "save") setBusy(elements.saveButton, false);
  }
}

function closeMenu() {
  if (!elements.menu || !elements.menuToggle) return;
  elements.menu.hidden = true;
  elements.menuToggle.setAttribute("aria-expanded", "false");
  elements.menuToggle.setAttribute("aria-label", t("intake.openMenu", "打开菜单"));
}

function toggleMenu() {
  if (!elements.menu || !elements.menuToggle) return;
  const willOpen = elements.menu.hidden;
  elements.menu.hidden = !willOpen;
  elements.menuToggle.setAttribute("aria-expanded", String(willOpen));
  elements.menuToggle.setAttribute("aria-label", willOpen ? t("intake.closeMenu", "关闭菜单") : t("intake.openMenu", "打开菜单"));
  if (willOpen) elements.menu.querySelector("a")?.focus();
}

async function initialize() {
  elements.submitForm?.addEventListener("submit", startIntake);
  elements.confirmForm?.addEventListener("submit", createFreePreview);
  elements.saveButton?.addEventListener("click", saveProject);
  elements.takePhotoButton?.addEventListener("click", () => elements.photos?.click());
  await loadLocationFields();
  elements.source?.addEventListener("input", () => {
    updateSourceCount();
    updateProgressRail();
  });
  elements.assetType?.addEventListener("change", () => {
    state.assetType = elements.assetType.value;
    elements.assetType.removeAttribute("aria-invalid");
    updateProgressRail();
  });
  elements.files?.addEventListener("change", () => {
    updateFilePresentation();
    updateProgressRail();
  });
  elements.photos?.addEventListener("change", () => {
    updatePhotoPresentation();
    updateProgressRail();
  });
  elements.prefecture?.addEventListener("change", () => {
    if (!applyingLocationPrefill) elements.prefecture.dataset.userModified = "true";
    populateCities(elements.prefecture.value);
    if (elements.city) elements.city.dataset.userModified = "";
    if (elements.ward) {
      elements.ward.dataset.userModified = "";
      resetLocationSelect(elements.ward, t("intake.selectWard", "请先选择区"));
    }
  });
  elements.city?.addEventListener("change", () => {
    if (!applyingLocationPrefill) elements.city.dataset.userModified = "true";
    populateWards(elements.prefecture?.value || "", elements.city.value);
    if (elements.ward) elements.ward.dataset.userModified = "";
  });
  elements.ward?.addEventListener("change", () => {
    if (!applyingLocationPrefill) elements.ward.dataset.userModified = "true";
  });
  elements.fileDropzone?.addEventListener("dragover", (event) => {
    event.preventDefault();
    elements.fileDropzone?.classList.add("is-dragover");
  });
  elements.fileDropzone?.addEventListener("dragleave", () => {
    elements.fileDropzone?.classList.remove("is-dragover");
  });
  elements.fileDropzone?.addEventListener("drop", handleFileDrop);
  document.querySelectorAll("input[name='purpose']").forEach((input) => {
    input.addEventListener("change", updateProgressRail);
  });
  document.querySelectorAll("[data-field]").forEach((input) => {
    input.addEventListener("input", updateProgressRail);
  });
  elements.projectName?.addEventListener("input", () => {
    state.projectNameTouched = true;
    elements.projectName?.removeAttribute("aria-invalid");
    if (elements.projectNameHelp) elements.projectNameHelp.textContent = t("intake.projectNameHelpRuntime", "保存时会使用这个名称；同一用户下名称不能重复。");
  });
  elements.menuToggle?.addEventListener("click", toggleMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && elements.menu && !elements.menu.hidden) {
      closeMenu();
      elements.menuToggle?.focus();
    }
  });
  elements.status?.classList.add("is-empty");
  if (elements.status) elements.status.textContent = "";
  if (DEMO_MODE) {
    document.querySelector("#demoBanner")?.removeAttribute("hidden");
    document.querySelector("#reviewLink")?.removeAttribute("hidden");
    setStatus(t("intake.demoModeEnabled", "界面演示已开启：可以依次体验提交、确认、预览和保存。"), "info");
  }
  updateSourceCount();
  updateFilePresentation();
  updatePhotoPresentation();
  if (elements.locationCandidate) elements.locationCandidate.textContent = t("intake.notObtained", "尚未获取");
  if (elements.assetType) elements.assetType.value = state.assetType;
  if (elements.assetTypeSummary) elements.assetTypeSummary.textContent = previewLabel(ASSET_TYPE_LABELS[state.assetType], t("intake.notSelected", "未选择"));
  updateProgressRail();
  if (state.session?.sessionId && state.session?.rawToken && state.assetType) {
    setStage("confirm");
    setStatus(t("intake.sessionRestored", "已恢复本次临时项目，请继续核对字段。"), "info");
  } else {
    setStage("submit");
    if (state.session?.sessionId && state.session?.rawToken) {
      setStatus(t("intake.sessionMissingAssetType", "当前临时项目缺少物件类型，请重新选择后提交。"), "info");
    }
  }
}

window.addEventListener("zou:recognition-prefill", (event) => applyLocationPrefill(event.detail || {}));
initialize();

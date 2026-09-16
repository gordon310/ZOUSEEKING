import { getValidAccessToken } from "./api-client.js?v=20260916-r37";
import { currencyForRegion, inferRegion, reportAccessState, reportCoverageState, selectPrice } from "./report-page-core.js?v=20260916-r37";

const PRODUCT_CODE = "risk_report_single";
const params = new URL(window.location.href).searchParams;
const queryKey = params.get("key") || params.get("query_key") || "";
const apiBase = (window.ZOUSEEKING_API_BASE_URL || "").replace(/\/$/, "");
const elements = {
  status: document.querySelector("#reportStatus"),
  content: document.querySelector("#reportContent"),
  title: document.querySelector("#reportTitle"),
  address: document.querySelector("#reportAddress"),
  generatedAt: document.querySelector("#reportGeneratedAt"),
  source: document.querySelector("#reportSource"),
  summary: document.querySelector("#reportSummaryText"),
  paywall: document.querySelector("#reportPaywall"),
  price: document.querySelector("#reportPrice"),
  login: document.querySelector("#reportLoginButton"),
  unlock: document.querySelector("#reportUnlockButton"),
  details: document.querySelector("#reportDetails"),
  insufficientData: document.querySelector("#reportInsufficientData"),
  download: document.querySelector("#reportDownloadButton"),
};

function t(key, fallback) {
  return window.ZouI18n?.t(key, fallback) || fallback;
}

function setStatus(message, tone = "") {
  elements.status.textContent = message;
  elements.status.classList.toggle("report-error", tone === "error");
}

function setText(element, value) {
  element.textContent = value == null ? "" : String(value);
}

function interp(text, params = {}) {
  return String(text).replace(/\{(\w+)\}/g, (match, key) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : match,
  );
}

function formatDate(value) {
  if (!value) return t("report.notAvailable", "—");
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function freeValue(report, ...keys) {
  for (const key of keys) {
    if (report?.[key] != null && typeof report[key] !== "object") return report[key];
    if (report?.metadata?.[key] != null && typeof report.metadata[key] !== "object") return report.metadata[key];
  }
  return "";
}

function renderFreeReport(report) {
  setText(elements.title, freeValue(report, "title") || t("report.titleFallback", "物件报告"));
  setText(elements.address, freeValue(report, "address", "location") || freeValue(report, "title") || t("report.addressUnavailable", "未标注地区"));
  setText(elements.generatedAt, formatDate(freeValue(report, "generated_at", "created_at")));
  setText(elements.source, freeValue(report, "data_sources", "source", "source_label") || t("report.sourceUnavailable", "以报告标注为准"));
  const summary = report?.summary;
  setText(elements.summary, typeof summary === "string" ? summary : summary?.line || summary?.title || freeValue(report, "overview") || t("report.summaryUnavailable", "暂无概要"));
}

async function downloadReport() {
  const token = await getValidAccessToken();
  if (!token) {
    setStatus(t("auth.sessionExpired", "登录状态已过期，请重新登录。"), "error");
    return;
  }
  elements.download.disabled = true;
  setStatus(t("report.downloadPreparing", "正在准备下载……"));
  try {
    const response = await fetch(`${apiBase}/api/reports/${encodeURIComponent(queryKey)}/download`, {
      headers: { Accept: "text/html", Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      const error = new Error(payload?.detail?.message || payload?.detail || "download_failed");
      error.code = payload?.detail?.code || "";
      throw error;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "report.html";
    link.click();
    URL.revokeObjectURL(url);
    setStatus(t("report.downloadComplete", "报告已下载。"), "success");
  } catch {
    setStatus(t("report.downloadFailed", "报告下载失败，请稍后重试。"), "error");
  } finally {
    elements.download.disabled = false;
  }
}

async function request(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  const token = await getValidAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${apiBase}${path}`, { ...options, headers });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload?.detail || `API ${response.status}`);
  return payload;
}

function regionFromBrowser() {
  return inferRegion({ queryRegion: params.get("region"), language: navigator.language, timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone });
}

function priceLabel(price) {
  if (!price) return "";
  const amount = Number(price.amount_minor);
  if (!Number.isFinite(amount)) return "";
  return new Intl.NumberFormat(document.documentElement.lang || "zh-CN", { style: "currency", currency: price.currency }).format(amount / 100);
}

async function preparePaywall(report) {
  elements.paywall.hidden = false;
  const token = await getValidAccessToken();
  if (!token) {
    if (window.ZouAuthSession?.read?.()?.provider === "supabase") {
      setStatus(t("auth.sessionExpired", "登录状态已过期，请重新登录。"), "error");
    }
    elements.login.hidden = false;
    elements.unlock.hidden = true;
    elements.login.href = `mypage.html?return=${encodeURIComponent(`report.html?key=${queryKey}`)}`;
    return;
  }
  elements.login.hidden = true;
  elements.unlock.hidden = false;
  const region = regionFromBrowser();
  const currency = currencyForRegion(region);
  try {
    const prices = await request("/api/billing/prices");
    const price = selectPrice(prices, PRODUCT_CODE, currency);
    setText(elements.price, price ? priceLabel(price) : t("report.priceUnavailable", "当前地区暂未提供价格"));
    elements.unlock.disabled = !price;
    elements.unlock.textContent = interp(
      t("report.unlockWithPrice", "解锁本报告（{price}）"),
      { price: priceLabel(price) },
    );
    elements.unlock.onclick = () => startCheckout(region);
  } catch {
    setText(elements.price, t("report.priceUnavailable", "当前地区暂未提供价格"));
    elements.unlock.disabled = true;
  }
}

async function startCheckout(region) {
  elements.unlock.disabled = true;
  setStatus(t("report.redirectingPayment", "正在前往支付页面……"), "");
  try {
    const checkout = await request("/api/billing/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_code: PRODUCT_CODE, subject_id: queryKey, region }),
    });
    if (!checkout?.url) throw new Error("missing checkout url");
    window.location.assign(checkout.url);
  } catch {
    elements.unlock.disabled = false;
    setStatus(t("report.paymentFailed", "支付发起失败，请稍后重试"), "error");
  }
}

async function pollAfterPayment() {
  setStatus(t("report.paymentProcessing", "支付处理中，请稍候……"));
  const startedAt = Date.now();
  let delay = 1000;
  while (Date.now() - startedAt < 60000) {
    try {
      const report = await request(`/api/reports/${encodeURIComponent(queryKey)}`);
      if (reportAccessState(report) === "unlocked") {
        renderReport(report);
        setStatus(t("report.paymentComplete", "报告已解锁"));
        return;
      }
    } catch {
      // Keep polling transient checkout/webhook propagation failures.
    }
    await new Promise((resolve) => window.setTimeout(resolve, delay));
    delay = Math.min(Math.round(delay * 1.5), 8000);
  }
  setStatus(t("report.paymentTimeout", "支付处理中，请稍后刷新"));
}

function renderReport(report) {
  elements.content.hidden = false;
  renderFreeReport(report);
  const coverage = reportCoverageState(report);
  if (elements.insufficientData) elements.insufficientData.hidden = coverage !== "insufficient_data";
  if (coverage === "insufficient_data") {
    elements.paywall.hidden = true;
    elements.details.hidden = true;
    return;
  }
  const unlocked = reportAccessState(report) === "unlocked";
  elements.paywall.hidden = unlocked;
  elements.details.hidden = !unlocked;
  if (unlocked) {
    elements.download.hidden = false;
    elements.download.onclick = downloadReport;
  } else {
    elements.download.hidden = true;
    void preparePaywall(report);
  }
}

async function init() {
  window.ZouI18n?.apply(document);
  if (!queryKey) {
    setStatus(t("report.missingKey", "缺少报告标识"), "error");
    return;
  }
  if (params.get("cancel") === "1" || params.get("payment") === "cancel") {
    setStatus(t("report.paymentCancelled", "支付已取消，可以随时重新尝试解锁"));
  }
  try {
    const report = await request(`/api/reports/${encodeURIComponent(queryKey)}`);
    renderReport(report);
    if (params.get("payment") === "success" || params.get("checkout") === "success") await pollAfterPayment();
  } catch (error) {
    setStatus(
      error?.code === "auth_session_expired"
        ? t("auth.sessionExpired", "登录状态已过期，请重新登录。")
        : t("report.loadFailed", "报告读取失败，请稍后重试"),
      "error",
    );
  }
}

init();

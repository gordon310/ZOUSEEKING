import { getExistingAccessToken } from "./api-client.js";

const API_BASE_URL = (window.ZOUSEEKING_API_BASE_URL || "").replace(/\/+$/, "");
const t = (key, fallback) => window.ZouI18n?.t(key, fallback) || fallback;
const imageInput = document.querySelector("#propertyPhotos");
const locationStatus = document.querySelector("#locationStatus");

function setLocationStatus(message, tone = "") {
  if (!locationStatus) return;
  locationStatus.textContent = message;
  locationStatus.dataset.tone = tone;
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error(t("recognition.invalidImage", "图片无法读取，请换一张 JPEG、PNG 或 WEBP 图片。")));
    reader.readAsDataURL(file);
  });
}

function saveLocationPrefill(location) {
  const prefill = {
    prefecture: location.prefecture || "",
    city: location.city || "",
    ward: location.ward || "",
  };
  sessionStorage.setItem("zou_recognition_prefill", JSON.stringify(prefill));
  window.dispatchEvent(new CustomEvent("zou:recognition-prefill", { detail: prefill }));
}

function formatLocation(location) {
  return [location?.prefecture, location?.city, location?.ward].filter(Boolean).join(" ");
}

async function resolveLocation(file) {
  const accessToken = getExistingAccessToken();
  if (!accessToken || !API_BASE_URL) {
    setLocationStatus(t("recognition.locationFailed", "照片位置识别失败,请手动填写"), "error");
    return;
  }
  setLocationStatus(t("recognition.locationLoading", "正在识别照片位置…"));
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 15000);
  try {
    const image = await fileToDataUrl(file);
    const response = await fetch(`${API_BASE_URL}/api/recognition`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ image, resolve_location_only: true }),
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error("recognition_failed");
    if (payload.location) {
      saveLocationPrefill(payload.location);
      const locationText = formatLocation(payload.location);
      setLocationStatus(
        `${t("recognition.locationFound", "已根据照片位置自动填入")}${locationText ? `: ${locationText}` : ""}`,
        "success",
      );
    } else {
      setLocationStatus(t("recognition.noLocation", "照片未包含位置信息,请手动填写"), "info");
    }
  } catch {
    setLocationStatus(t("recognition.locationFailed", "照片位置识别失败,请手动填写"), "error");
  } finally {
    window.clearTimeout(timeoutId);
  }
}

imageInput?.addEventListener("change", () => {
  const file = imageInput.files?.[0];
  if (file) resolveLocation(file);
});

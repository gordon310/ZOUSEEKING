import { getExistingAccessToken } from "./api-client.js";

const API_BASE_URL = (window.ZOUSEEKING_API_BASE_URL || "").replace(/\/+$/, "");
const t = (key, fallback) => window.ZouI18n?.t(key, fallback) || fallback;
const imageInput = document.querySelector("#recognitionImage");
const locationButton = document.querySelector("#recognitionLocationButton");
const locationStatus = document.querySelector("#recognitionLocationStatus");

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
  sessionStorage.setItem("zou_recognition_prefill", JSON.stringify({
    prefecture: location.prefecture || "",
    city: location.city || "",
    ward: location.ward || "",
  }));
}

function formatLocation(location) {
  return [location?.prefecture, location?.city, location?.ward].filter(Boolean).join(" ");
}

async function resolveLocation(file) {
  const accessToken = getExistingAccessToken();
  if (!accessToken || !API_BASE_URL) return;
  locationButton.disabled = true;
  setLocationStatus(t("recognition.locationLoading", "正在读取照片 EXIF 位置……"));
  try {
    const image = await fileToDataUrl(file);
    const response = await fetch(`${API_BASE_URL}/api/recognition`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ image, resolve_location_only: true }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.detail?.message || t("recognition.locationFailed", "照片位置读取失败，请手动填写或用设备定位。"));
    if (payload.location) {
      saveLocationPrefill(payload.location);
      setLocationStatus(`${t("recognition.locationFound", "照片位置已识别")}:${formatLocation(payload.location)}(${t("recognition.locationSource", "来源:照片 EXIF")})`, "success");
    } else {
      setLocationStatus(t("recognition.noLocation", "照片不包含位置信息,请手动填写或用设备定位"), "info");
    }
  } catch (error) {
    setLocationStatus(error.message || t("recognition.locationFailed", "照片位置读取失败，请手动填写或用设备定位。"), "error");
  } finally {
    locationButton.disabled = false;
  }
}

imageInput?.addEventListener("change", () => {
  const file = imageInput.files?.[0];
  if (file) resolveLocation(file);
});
locationButton?.addEventListener("click", () => {
  const file = imageInput.files?.[0];
  if (file) resolveLocation(file);
});

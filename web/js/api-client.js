const API_BASE_URL = (window.ZOUSEEKING_API_BASE_URL || "").replace(/\/$/, "");

function parseResponse(response, text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request(path, { method = "GET", body, sessionToken = "", accessToken = "" } = {}) {
  const headers = { Accept: "application/json" };
  let requestBody = body;
  if (sessionToken) headers["X-Analysis-Session"] = sessionToken;
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (body && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    requestBody = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: requestBody,
    });
  } catch (error) {
    throw new Error("暂时无法连接分析服务，请检查网络后重试。", { cause: error });
  }

  const payload = parseResponse(response, await response.text());
  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? payload.detail || payload.message : payload;
    const message = detail && typeof detail === "object" ? detail.message : detail;
    const error = new Error(message || `分析服务请求失败（${response.status}）。`);
    error.status = response.status;
    error.code = detail && typeof detail === "object" ? detail.code || "" : payload?.code || "";
    error.payload = payload;
    throw error;
  }
  return payload;
}

export function createSession(purpose, consentVersion = "privacy-2026-08") {
  return request("/api/intake/sessions", {
    method: "POST",
    body: { purpose, consent_version: consentVersion },
  });
}

export function addTextOrUrlInput(sessionId, sessionToken, value) {
  const trimmed = value.trim();
  const isUrl = /^https:\/\/\S+$/i.test(trimmed);
  return request(`/api/intake/sessions/${encodeURIComponent(sessionId)}/inputs`, {
    method: "POST",
    sessionToken,
    body: isUrl ? { input_type: "url", source_url: trimmed } : { input_type: "text", raw_text: trimmed },
  });
}

export async function uploadFiles(sessionId, sessionToken, files) {
  const results = [];
  for (const file of files) {
    const body = new FormData();
    body.append("file", file, file.name);
    results.push(
      await request(`/api/intake/sessions/${encodeURIComponent(sessionId)}/files`, {
        method: "POST",
        sessionToken,
        body,
      }),
    );
  }
  return results;
}

export function confirmField(
  sessionId,
  sessionToken,
  fieldName,
  value,
  confirmationStatus = "confirmed",
  { locator = "" } = {},
) {
  const body = { field_name: fieldName, value, confirmation_status: confirmationStatus };
  if (locator) body.locator = locator;
  return request(
    `/api/intake/sessions/${encodeURIComponent(sessionId)}/fields/${encodeURIComponent(fieldName)}`,
    {
      method: "PUT",
      sessionToken,
      body,
    },
  );
}

export function saveLocation(sessionId, sessionToken, payload) {
  return request(`/api/intake/sessions/${encodeURIComponent(sessionId)}/location`, {
    method: "PUT",
    sessionToken,
    body: payload,
  });
}

export function generatePreview(sessionId, sessionToken) {
  return request(`/api/intake/sessions/${encodeURIComponent(sessionId)}/preview`, {
    method: "POST",
    sessionToken,
  });
}

export function convertSession(sessionId, sessionToken, accessToken, projectName = "") {
  return request(`/api/intake/sessions/${encodeURIComponent(sessionId)}/convert`, {
    method: "POST",
    sessionToken,
    accessToken,
    body: projectName.trim() ? { project_name: projectName.trim() } : {},
  });
}

export function getExistingAccessToken() {
  const directSession = window.ZOUSEEKING_AUTH_SESSION || window.__ZOUSEEKING_AUTH_SESSION__;
  if (directSession && typeof directSession.accessToken === "string") return directSession.accessToken;

  try {
    const sessionStorageValue = window.sessionStorage.getItem("zou_house_auth_session");
    const sessionStorageSession = sessionStorageValue ? JSON.parse(sessionStorageValue) : null;
    if (sessionStorageSession?.accessToken) return sessionStorageSession.accessToken;
  } catch {
    // A blocked storage area should not break the anonymous intake page.
  }

  // The existing website stores its already-established auth session here. This page only reads it;
  // anonymous intake data is always stored in sessionStorage by property-intake.js.
  try {
    const legacyValue = window.localStorage.getItem("zou_house_session");
    const legacySession = legacyValue ? JSON.parse(legacyValue) : null;
    return legacySession?.provider === "supabase" ? legacySession.accessToken || "" : "";
  } catch {
    return "";
  }
}

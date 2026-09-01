const SESSION_KEY = "zou_house_session";
const QUERY_HISTORY_KEY = "zou_house_query_history";
const PASSWORD_MIN_LENGTH = 12;
const PASSWORD_MAX_LENGTH = 128;
const SESSION_PROVIDERS = new Set(["supabase", "demo"]);
const API_BASE_URL = (window.ZOUSEEKING_API_BASE_URL || localStorage.getItem("zou_house_api_base") || "").replace(/\/$/, "");
const SUPABASE_URL = (window.ZOUSEEKING_SUPABASE_URL || localStorage.getItem("zou_house_supabase_url") || "").replace(/\/$/, "");
const SUPABASE_ANON_KEY = window.ZOUSEEKING_SUPABASE_ANON_KEY || localStorage.getItem("zou_house_supabase_anon_key") || "";
const PRIVACY_POLICY_VERSION = "privacy-2026-08";
const TERMS_VERSION = "terms-2026-08";
const ACCOUNT_DELETION_CONFIRMATION = "DELETE_ACCOUNT";

const DEFAULT_FIELD_OPTIONS = {
  prefectures: [
    "北海道",
    "青森县",
    "岩手县",
    "宫城县",
    "秋田县",
    "山形县",
    "福岛县",
    "茨城县",
    "栃木县",
    "群马县",
    "埼玉县",
    "千叶县",
    "东京都",
    "神奈川县",
    "新潟县",
    "富山县",
    "石川县",
    "福井县",
    "山梨县",
    "长野县",
    "岐阜县",
    "静冈县",
    "爱知县",
    "三重县",
    "滋贺县",
    "京都府",
    "大阪府",
    "兵库县",
    "奈良县",
    "和歌山县",
    "鸟取县",
    "岛根县",
    "冈山县",
    "广岛县",
    "山口县",
    "德岛县",
    "香川县",
    "爱媛县",
    "高知县",
    "福冈县",
    "佐贺县",
    "长崎县",
    "熊本县",
    "大分县",
    "宫崎县",
    "鹿儿岛县",
    "冲绳县",
  ],
  cities: {
    北海道: ["札幌市"],
    青森县: ["青森市"],
    岩手县: ["盛冈市"],
    宫城县: ["仙台市"],
    秋田县: ["秋田市"],
    山形县: ["山形市"],
    福岛县: ["福岛市"],
    茨城县: ["水户市"],
    栃木县: ["宇都宫市"],
    群马县: ["前桥市"],
    埼玉县: ["埼玉市"],
    千叶县: ["千叶市"],
    东京都: ["东京23区"],
    神奈川县: ["横滨市"],
    新潟县: ["新潟市"],
    富山县: ["富山市"],
    石川县: ["金泽市"],
    福井县: ["福井市"],
    山梨县: ["甲府市"],
    长野县: ["长野市"],
    岐阜县: ["岐阜市"],
    静冈县: ["静冈市"],
    爱知县: ["名古屋市"],
    三重县: ["津市"],
    滋贺县: ["大津市"],
    京都府: ["京都市"],
    大阪府: ["大阪市"],
    兵库县: ["神户市"],
    奈良县: ["奈良市"],
    和歌山县: ["和歌山市"],
    鸟取县: ["鸟取市"],
    岛根县: ["松江市"],
    冈山县: ["冈山市"],
    广岛县: ["广岛市"],
    山口县: ["山口市"],
    德岛县: ["德岛市"],
    香川县: ["高松市"],
    爱媛县: ["松山市"],
    高知县: ["高知市"],
    福冈县: ["福冈市"],
    佐贺县: ["佐贺市"],
    长崎县: ["长崎市"],
    熊本县: ["熊本市"],
    大分县: ["大分市"],
    宫崎县: ["宫崎市"],
    鹿儿岛县: ["鹿儿岛市"],
    冲绳县: ["那霸市"],
  },
  wards: {
    "东京都::东京23区": [
        "千代田区",
        "中央区",
        "港区",
        "新宿区",
        "文京区",
        "台东区",
        "墨田区",
        "江东区",
        "品川区",
        "目黑区",
        "大田区",
        "世田谷区",
        "涩谷区",
        "中野区",
        "杉并区",
        "丰岛区",
        "北区",
        "荒川区",
        "板桥区",
        "练马区",
        "足立区",
        "葛饰区",
        "江户川区",
    ],
    "大阪府::大阪市": [
        "北区",
        "都岛区",
        "福岛区",
        "此花区",
        "中央区",
        "西区",
        "港区",
        "大正区",
        "天王寺区",
        "浪速区",
        "西淀川区",
        "淀川区",
        "东淀川区",
        "东成区",
        "生野区",
        "旭区",
        "城东区",
        "鹤见区",
        "阿倍野区",
        "住之江区",
        "住吉区",
        "东住吉区",
        "平野区",
        "西成区",
    ],
    "神奈川县::横滨市": [
        "鹤见区",
        "神奈川区",
        "西区",
        "中区",
        "南区",
        "港南区",
        "保土谷区",
        "旭区",
        "矶子区",
        "金泽区",
        "港北区",
        "绿区",
        "青叶区",
        "都筑区",
        "户塚区",
        "荣区",
        "泉区",
        "濑谷区",
    ],
  },
  assetTypes: ["塔楼", "公寓", "一户建"],
  years: ["2024", "2025", "2026", "2027"],
  months: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
};

function readJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback));
  } catch {
    localStorage.removeItem(key);
    return fallback;
  }
}

const state = {
  records: [],
  query: "",
  queryOptions: null,
  page: 1,
  selectedId: "",
  session: readJson(SESSION_KEY, null),
  fieldOptions: DEFAULT_FIELD_OPTIONS,
  myTasks: [],
  myPageLoaded: false,
  profile: null,
  profileLoaded: false,
  profileEditing: false,
  authMode: "login",
  messageTimer: null,
  compareIds: [],
};

const $ = (selector) => document.querySelector(selector);

function uiText(key, fallback = "") {
  return window.ZouI18n?.t(key, fallback) || fallback;
}

function formatUiText(key, fallback = "", values = {}) {
  return uiText(key, fallback).replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ""));
}

function on(selector, eventName, handler) {
  const element = $(selector);
  if (element) element.addEventListener(eventName, handler);
}

function compact(text) {
  return String(text || "").toLowerCase().replace(/\s+/g, "");
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function readRegistrationConsent() {
  const checkbox = $("#registerConsent");
  if (!checkbox?.checked) {
    setMessage(uiText("account.consentRequired", "请先阅读并同意隐私政策和服务条款。"), "error");
    checkbox?.focus();
    return null;
  }
  return {
    consentVersion: PRIVACY_POLICY_VERSION,
    termsVersion: TERMS_VERSION,
    consentAt: new Date().toISOString(),
  };
}

function getQueryHistory() {
  return readJson(QUERY_HISTORY_KEY, []);
}

function saveQueryHistory(items) {
  localStorage.setItem(QUERY_HISTORY_KEY, JSON.stringify(items.slice(0, 30)));
}

function passwordIsValid(password) {
  return (
    typeof password === "string" &&
    password.length >= PASSWORD_MIN_LENGTH &&
    password.length <= PASSWORD_MAX_LENGTH &&
    !/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/.test(password)
  );
}

function hasSupabaseSession() {
  return hasSupabase() && state.session?.provider === "supabase" && Boolean(state.session?.accessToken);
}

function isLoggedIn() {
  return Boolean(state.session?.username && SESSION_PROVIDERS.has(state.session?.provider));
}

function setMessage(text, tone = "") {
  const message = $("#formMessage");
  if (!message) return;
  if (state.messageTimer) {
    clearTimeout(state.messageTimer);
    state.messageTimer = null;
  }
  message.textContent = text;
  message.className = `form-message ${tone}`;
  if (text && tone === "success") {
    state.messageTimer = setTimeout(() => {
      message.textContent = "";
      message.className = "form-message";
      state.messageTimer = null;
    }, 2200);
  }
}

function recordMatches(record) {
  if (!isLoggedIn()) return true;
  if (state.queryOptions) return recordMatchesOptions(record, state.queryOptions);
  const q = compact(state.query);
  if (!q) return true;
  return compact(record.search_text || `${record.title} ${record.publish_month}`).includes(q);
}

function inferRecordLocation(record) {
  const title = record.title || "";
  if (title.startsWith("东京")) {
    return { prefecture: "东京都", city: "东京23区", ward: title.replace(/^东京/, "").split("塔楼")[0] };
  }
  if (title.startsWith("大阪")) {
    return { prefecture: "大阪府", city: "大阪市", ward: title.replace(/^大阪/, "").split("塔楼")[0] };
  }
  if (title.startsWith("横滨")) {
    return { prefecture: "神奈川县", city: "横滨市", ward: title.replace(/^横滨/, "").split("塔楼")[0] };
  }
  return { prefecture: "", city: "", ward: "" };
}

function recordMatchesOptions(record, options) {
  const loc = inferRecordLocation(record);
  const monthText = `${options.year}年${Number(options.month)}月`;
  if (options.prefecture && loc.prefecture !== options.prefecture) return false;
  if (options.city && loc.city !== options.city) return false;
  if (options.ward && loc.ward !== options.ward) return false;
  if (options.assetType && options.assetType !== "塔楼" && record.asset_type !== options.assetType) return false;
  if (options.assetType === "塔楼" && !compact(record.title).includes("塔楼")) return false;
  if (options.year && !String(record.publish_month || "").includes(`${options.year}年`)) return false;
  if (options.month && record.publish_month !== monthText) return false;
  return true;
}

function displayPropertyText(value) {
  return String(value ?? "")
    .replaceAll("日本房产", "日本物件")
    .replaceAll("房产", "物件")
    .replaceAll("房源", "物件")
    .replaceAll("房屋", "物件")
    .replaceAll("房型", "物件类型");
}

function queryTitle(options) {
  const area = [options.prefecture, options.city, options.ward].filter(Boolean).join("");
  return `${area || "日本"}${displayPropertyText(options.assetType)}｜${options.year}年${Number(options.month)}月`;
}

function queryKey(options) {
  return [options.prefecture, options.city, options.ward || "全部区", options.assetType, options.year, Number(options.month)].join("::");
}

function xhsDraftFromQuery(options) {
  const title = queryTitle(options);
  return `# ${title}\n\n## 小红书发布内容\n${title}，租还是买？\n\n数据生成中。已有相同查询会直接调取历史数据；没有的话，JPHOUSE 会按备用数据源抓取租房子、买房子、物件类型与面积、日元/RMB、总而言之。`;
}

function hasBackend() {
  return Boolean(API_BASE_URL);
}

function canUseAuthenticatedBackend() {
  return hasBackend() && state.session?.provider === "supabase" && Boolean(state.session?.accessToken);
}

function hasSupabase() {
  return Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
}

function appRedirectUrl() {
  const url = new URL(window.location.href);
  url.hash = "";
  url.search = "";
  return url.toString();
}

function cloneDefaultFieldOptions() {
  return JSON.parse(JSON.stringify(DEFAULT_FIELD_OPTIONS));
}

function normalizeFieldOptions(rows = [], baseOptions = cloneDefaultFieldOptions()) {
  const options = JSON.parse(JSON.stringify(baseOptions));
  const next = {
    prefectures: [],
    cities: {},
    wards: {},
    assetTypes: [],
    years: [],
    months: [],
  };
  for (const row of rows) {
    if (!row?.is_active) continue;
    const value = row.value;
    if (!value) continue;
    if (row.option_type === "prefecture") {
      next.prefectures.push(value);
    }
    if (row.option_type === "city") {
      const parent = row.parent_value || "";
      if (!next.cities[parent]) next.cities[parent] = [];
      next.cities[parent].push(value);
    }
    if (row.option_type === "ward") {
      const key = row.parent_value || "";
      if (!next.wards[key]) next.wards[key] = [];
      next.wards[key].push(value);
    }
    if (row.option_type === "asset_type") next.assetTypes.push(value);
    if (row.option_type === "year") next.years.push(value);
    if (row.option_type === "month") next.months.push(value);
  }
  return {
    prefectures: next.prefectures.length ? next.prefectures : options.prefectures,
    cities: Object.keys(next.cities).length ? next.cities : options.cities,
    wards: Object.keys(next.wards).length ? next.wards : options.wards,
    assetTypes: next.assetTypes.length ? next.assetTypes : options.assetTypes,
    years: next.years.length ? next.years : options.years,
    months: next.months.length ? next.months : options.months,
  };
}

async function loadFieldOptions() {
  state.fieldOptions = cloneDefaultFieldOptions();
  try {
    const response = await fetch("field-options.json", { cache: "no-store" });
    if (response.ok) {
      const localOptions = await response.json();
      state.fieldOptions = {
        ...cloneDefaultFieldOptions(),
        ...localOptions,
      };
    }
  } catch {
    state.fieldOptions = cloneDefaultFieldOptions();
  }
  if (!hasSupabase()) return;
  try {
    const rows = await supabaseFetch("/query_field_options?select=option_type,parent_value,value,label,sort_order,is_active&is_active=eq.true&order=option_type.asc,sort_order.asc,value.asc&limit=5000");
    if (Array.isArray(rows) && rows.length) {
      state.fieldOptions = normalizeFieldOptions(rows, state.fieldOptions);
    }
  } catch {
    // Keep local complete field-options.json/defaults when Supabase field table is not ready.
  }
}

async function supabaseAuthFetch(path, options = {}) {
  const authToken = options.authToken || SUPABASE_ANON_KEY;
  const response = await fetch(`${SUPABASE_URL}/auth/v1${path}`, {
    ...options,
    headers: {
      apikey: SUPABASE_ANON_KEY,
      Authorization: `Bearer ${authToken}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = text;
  }
  if (!response.ok) {
    const message = payload?.msg || payload?.message || payload?.error_description || payload?.error || text || `Supabase Auth ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

function saveSession(session) {
  state.session = session;
  if (session) {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } else {
    localStorage.removeItem(SESSION_KEY);
  }
}

function sessionFromAuth(data, fallback = {}) {
  const user = data?.user || fallback.user || {};
  const metadata = user.user_metadata || {};
  const email = user.email || fallback.email || "";
  const username = metadata.username || fallback.username || email.split("@")[0] || "小象用户";
  return {
    username,
    email,
    userId: user.id || fallback.userId || "",
    accessToken: data?.access_token || fallback.accessToken || "",
    refreshToken: data?.refresh_token || fallback.refreshToken || "",
    provider: "supabase",
  };
}

async function handleAuthRedirect() {
  if (!hasSupabase() || !window.location.hash) return;
  const params = new URLSearchParams(window.location.hash.slice(1));
  const error = params.get("error_description") || params.get("error");
  if (error) {
    history.replaceState(null, "", appRedirectUrl());
    setMessage("邮箱确认未完成，请重新发起确认链接。", "error");
    return;
  }
  const accessToken = params.get("access_token");
  const refreshToken = params.get("refresh_token");
  if (!accessToken) return;
  try {
    const user = await supabaseAuthFetch("/user", { authToken: accessToken });
    saveSession(
      sessionFromAuth(
        {
          access_token: accessToken,
          refresh_token: refreshToken || "",
          user,
        },
        {},
      ),
    );
    history.replaceState(null, "", appRedirectUrl());
    setMessage("邮箱确认成功，已经登录。可以开始搜房了。", "success");
  } catch {
    history.replaceState(null, "", appRedirectUrl());
    setMessage("邮箱确认成功但登录状态读取失败，请重新登录。", "error");
  }
}

async function refreshSupabaseSession() {
  if (!hasSupabase() || state.session?.provider !== "supabase") return;
  if (state.session.accessToken) {
    try {
      await supabaseAuthFetch("/user", { authToken: state.session.accessToken });
      return;
    } catch {
      // Try refresh token below.
    }
  }
  if (!state.session.refreshToken) {
    saveSession(null);
    return;
  }
  try {
    const data = await supabaseAuthFetch("/token?grant_type=refresh_token", {
      method: "POST",
      body: JSON.stringify({ refresh_token: state.session.refreshToken }),
    });
    saveSession(sessionFromAuth(data, state.session));
  } catch {
    saveSession(null);
  }
}

async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(state.session?.accessToken ? { Authorization: `Bearer ${state.session.accessToken}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `API ${response.status}`);
  }
  return response.json();
}

function backendReportToRecord(options, report) {
  const rental = report.rental || [];
  const sale = report.sale || [];
  const layouts = Array.from(new Set([...rental, ...sale].map((row) => row.layout).filter(Boolean))).sort();
  return {
    id: `${report.slug}::${report.publish_month}`,
    slug: report.slug,
    template_name: "jphouse",
    title: report.title,
    publish_month: report.publish_month,
    generated_at: new Date().toISOString(),
    regions: [options.prefecture, options.city, options.ward].filter(Boolean),
    asset_type: options.assetType,
    layouts,
    status: "generated",
    summary: report.summary || {},
    rental,
    sale,
    markdown: report.markdown || "",
    xhs_content: report.xhs_content || "",
    hashtags: [],
    data_sources: report.data_sources || [],
    images: report.images || [],
    search_text: compact([report.title, report.publish_month, options.prefecture, options.city, options.ward, options.assetType, report.markdown].join(" ")),
  };
}

function supabaseReportToRecord(options, report) {
  return backendReportToRecord(options, {
    slug: report.slug,
    title: report.title,
    publish_month: report.publish_month,
    markdown: report.markdown,
    xhs_content: report.xhs_content,
    rental: report.rental || [],
    sale: report.sale || [],
    summary: report.summary || {},
    images: report.images || [],
    data_sources: report.data_sources || [],
    raw_record: report.raw_record || {},
  });
}

function supabaseStoredReportToRecord(report) {
  const query = report.raw_record?.query || {};
  const inferred = inferRecordLocation({ title: report.title || "" });
  return backendReportToRecord(
    {
      prefecture: query.prefecture || inferred.prefecture || "",
      city: query.city || inferred.city || "",
      ward: query.ward || inferred.ward || "",
      assetType: query.asset_type || query.assetType || "",
    },
    report,
  );
}

async function loadRemoteReports() {
  if (!hasSupabase()) return;
  try {
    const rows = await supabaseFetch("/property_reports?select=*&order=created_at.desc&limit=300");
    (rows || []).forEach((row) => upsertRuntimeRecord(supabaseStoredReportToRecord(row)));
  } catch {
    // Static library is enough for the page to work; remote reports are a bonus.
  }
}

function upsertRuntimeRecord(record) {
  state.records = [record, ...state.records.filter((item) => item.id !== record.id)];
}

async function supabaseFetch(path, options = {}) {
  const response = await fetch(`${SUPABASE_URL}/rest/v1${path}`, {
    ...options,
    headers: {
      apikey: SUPABASE_ANON_KEY,
      Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Supabase ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function supabaseUserFetch(path, options = {}) {
  if (!state.session?.accessToken) throw new Error("登录状态过期，请重新登录。");
  const response = await fetch(`${SUPABASE_URL}/rest/v1${path}`, {
    ...options,
    headers: {
      apikey: SUPABASE_ANON_KEY,
      Authorization: `Bearer ${state.session.accessToken}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Supabase ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function supabaseFunctionFetch(name, payload = {}) {
  if (!state.session?.accessToken) throw new Error("登录状态过期，请重新登录。");
  const response = await fetch(`${SUPABASE_URL}/functions/v1/${name}`, {
    method: "POST",
    headers: {
      apikey: SUPABASE_ANON_KEY,
      Authorization: `Bearer ${state.session.accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    throw new Error(body?.error || body?.message || text || `Function ${response.status}`);
  }
  return body;
}

function rowLine(row) {
  const amount = [row.amount_jpy, row.amount_rmb].filter(Boolean).join(" / ");
  const unit = [row.unit_jpy, row.unit_rmb].filter(Boolean).join(" / ");
  return `${row.area}｜${amount}｜${unit}`;
}

function displayMarkdown(markdown) {
  const cleanMarkdown = String(markdown || "")
    .split("\n")
    .filter((line) => {
      const text = line.trim();
      if (text.startsWith("<!--")) return false;
      if (text === "吃饱饭，没事干，纯分享。") return false;
      if (text.startsWith("数据如有不对")) return false;
      if (/^#[^\s#]+(\s+#[^\s#]+)*$/.test(text)) return false;
      return true;
    })
    .join("\n")
    .trim();
  return displayPropertyText(cleanMarkdown);
}

function previewText(record) {
  const rental = record.rental?.[0];
  const sale = record.sale?.[0];
  const rent = rental ? `${rental.layout} 租 ${rental.amount_jpy} / ${rental.amount_rmb}` : "暂无租赁数据";
  const buy = sale ? `${sale.layout} 买 ${sale.amount_jpy} / ${sale.amount_rmb}` : "暂无买卖数据";
  return `${rent}；${buy}`;
}

function optionsFromQueryRow(query) {
  return {
    prefecture: query.prefecture,
    city: query.city,
    ward: query.ward || "",
    assetType: query.asset_type,
    year: String(query.year),
    month: String(query.month),
  };
}

function titleFromQueryRow(query) {
  return queryTitle(optionsFromQueryRow(query));
}

function latestJob(query) {
  const jobs = Array.isArray(query.generation_jobs) ? query.generation_jobs : [];
  return jobs[0] || null;
}

function statusLabel(query) {
  const job = latestJob(query);
  if (query.status === "completed") return uiText("status.completed", "已完成");
  if (job?.status === "running" || query.status === "running") return uiText("status.running", "生成中");
  if (job?.status === "failed") return uiText("status.failed", "失败");
  return uiText("status.waiting", "等待生成");
}

async function loadMyPage() {
  if (!isLoggedIn() || !state.session?.email) {
    state.myTasks = [];
    state.myPageLoaded = true;
    return;
  }
  if (canUseAuthenticatedBackend()) {
    state.myTasks = (await apiFetch("/api/my/queries")) || [];
    state.myPageLoaded = true;
    return;
  }
  if (!hasSupabaseSession()) {
    state.myTasks = [];
    state.myPageLoaded = true;
    return;
  }
  state.myTasks =
    (await supabaseUserFetch(
      `/queries?select=*,generation_jobs(id,status,progress,current_step,error_message,created_at)&owner_user_id=eq.${encodeURIComponent(state.session.userId)}&order=created_at.desc&limit=10`,
    )) || [];
  state.myPageLoaded = true;
}

async function ensureUserProfile() {
  if (
    !isLoggedIn() ||
    !hasSupabaseSession() ||
    !state.session?.userId ||
    window.ZOUSEEKING_REAL_OPERATIONS_DISABLED
  ) {
    state.profile = null;
    state.profileLoaded = true;
    return;
  }
  const userId = encodeURIComponent(state.session.userId);
  const rows = await supabaseUserFetch(`/user_profiles?select=*&user_id=eq.${userId}&limit=1`);
  if (rows?.[0]) {
    state.profile = rows[0];
    state.profileLoaded = true;
    return;
  }
  state.profile = null;
  state.profileLoaded = true;
}

function profileValue(key) {
  return state.profile?.[key] || "";
}

function renderProfile() {
  if (!$("#profileCard")) return;
  $("#profileCard").classList.toggle("hidden", !isLoggedIn());
  if (!isLoggedIn()) return;

  if (!hasSupabaseSession()) {
    $("#profileSummary").innerHTML = `<div class="empty">Supabase 还没配置，资料卡先不营业。</div>`;
    $("#profileForm").classList.add("hidden");
    return;
  }

  if (!state.profileLoaded) {
    $("#profileSummary").innerHTML = `<div class="empty">正在加载用户资料……</div>`;
    $("#profileForm").classList.add("hidden");
    return;
  }

  if (!state.profile) {
    $("#profileSummary").innerHTML = `<div class="empty">账户资料服务尚未开放，当前未创建或修改资料。</div>`;
    $("#profileForm").classList.add("hidden");
    return;
  }

  const profile = state.profile;
  const displayName = profile.display_name || profile.username || state.session.username;
  const tier = profile.membership_tier === "free" ? "免费版" : profile.membership_tier;
  $("#profileSummary").innerHTML = `
    <div class="profile-line"><span>昵称</span><strong>${escapeHtml(displayName)}</strong></div>
    <div class="profile-line"><span>邮箱</span><strong>${escapeHtml(profile.email || state.session.email)}</strong></div>
    <div class="profile-line"><span>会员</span><strong>${escapeHtml(tier)}｜每日 ${escapeHtml(profile.daily_query_limit || 3)} 次</strong></div>
    <div class="profile-line"><span>关注</span><strong>${escapeHtml(displayPropertyText([profile.favorite_area, profile.favorite_asset_type].filter(Boolean).join(" / ") || "还没填"))}</strong></div>
  `;

  $("#profileForm").classList.toggle("hidden", !state.profileEditing);
  $("#editProfileButton").textContent = state.profileEditing ? "收起" : "编辑";
  if (state.profileEditing) {
    $("#profileDisplayName").value = profile.display_name || profile.username || "";
    $("#profileEmail").value = profile.email || state.session.email || "";
    $("#profileCity").value = profile.city || "";
    $("#profileFavoriteArea").value = profile.favorite_area || "";
    $("#profileFavoriteAssetType").value = profile.favorite_asset_type || "";
    $("#profileBio").value = profile.bio || "";
  }
}

async function saveProfile(event) {
  event.preventDefault();
  if (!isLoggedIn() || !hasSupabaseSession() || !state.session?.userId) {
    setMessage("请先登录，再编辑资料。", "error");
    return;
  }
  if (window.ZOUSEEKING_REAL_OPERATIONS_DISABLED || !state.profile) {
    setMessage("账户资料服务尚未开放；未提交任何资料。", "error");
    return;
  }
  const payload = {
    display_name: $("#profileDisplayName").value.trim(),
    city: $("#profileCity").value.trim(),
    favorite_area: $("#profileFavoriteArea").value.trim(),
    favorite_asset_type: $("#profileFavoriteAssetType").value,
    bio: $("#profileBio").value.trim(),
  };
  try {
    const rows = await supabaseUserFetch(`/user_profiles?user_id=eq.${encodeURIComponent(state.session.userId)}`, {
      method: "PATCH",
      headers: { Prefer: "resolution=merge-duplicates,return=representation" },
      body: JSON.stringify(payload),
    });
    state.profile = rows?.[0] || payload;
    state.profileEditing = false;
    if (payload.display_name) {
      saveSession({ ...state.session, username: payload.display_name });
    }
    setMessage("资料已保存。小象记住了，但没有到处乱说。", "success");
    render();
  } catch {
    setMessage("资料保存服务暂时不可用，未提交任何资料。", "error");
  }
}

async function updatePassword(event) {
  event.preventDefault();
  if (!isLoggedIn() || !hasSupabaseSession()) {
    setMessage("请先登录，再改密码。", "error");
    return;
  }
  const password = $("#newPassword").value;
  const confirm = $("#confirmNewPassword").value;
  if (!passwordIsValid(password)) {
    setMessage("新密码需为 12–128 位，且不能包含控制字符。", "error");
    return;
  }
  if (password !== confirm) {
    setMessage("两次密码不一样。手滑，是人类共同命运。", "error");
    return;
  }
  const submitButton = $("#passwordForm button[type='submit']");
  try {
    submitButton.disabled = true;
    await supabaseAuthFetch("/user", {
      method: "PUT",
      authToken: state.session.accessToken,
      body: JSON.stringify({ password }),
    });
    $("#passwordForm").reset();
    setMessage("密码已更新。下次登录请用新密码，小象已换锁。", "success");
  } catch {
    setMessage("密码更新未完成，请稍后再试。", "error");
  } finally {
    submitButton.disabled = false;
  }
}

async function requestAccountDeletion() {
  const confirmation = $("#deleteAccountConfirm");
  if (!confirmation?.checked) {
    setMessage(uiText("account.deleteRequired", "请勾选确认后再提交删除申请。"), "error");
    confirmation?.focus();
    return;
  }
  $("#deleteAccountDialog")?.close();
  if (!isLoggedIn() || state.session?.provider !== "supabase" || !state.session?.accessToken || !hasBackend()) {
    setMessage(uiText("account.deleteUnavailable", "账户删除服务尚未接通，未删除任何内容；请查看客服入口。"), "error");
    return;
  }
  const submitButton = $("#confirmDeleteAccountButton");
  try {
    if (submitButton) submitButton.disabled = true;
    setMessage(uiText("account.deleteSubmitting", "正在提交删除申请……"));
    await apiFetch("/api/account/deletion-request", {
      method: "POST",
      body: JSON.stringify({
        privacy_policy_version: PRIVACY_POLICY_VERSION,
        terms_version: TERMS_VERSION,
        confirmation: ACCOUNT_DELETION_CONFIRMATION,
      }),
    });
    await logout();
    setMessage(uiText("account.deleteSubmitted", "删除申请已提交；当前会话已退出，请留意客服确认。"), "success");
  } catch {
    setMessage(uiText("account.deleteFailed", "删除申请未完成，未删除任何内容；请查看客服入口。"), "error");
  } finally {
    if (submitButton) submitButton.disabled = false;
    if (confirmation) confirmation.checked = false;
  }
}

function renderMyPage() {
  const panel = $("#mypagePanel");
  if (!panel) return;
  panel.classList.toggle("hidden", !isLoggedIn());
  if (!isLoggedIn()) return;

  const tasks = state.myTasks || [];
  const completed = tasks.filter((task) => task.status === "completed").length;
  const pending = tasks.filter((task) => task.status !== "completed").length;
  if ($("#myStats")) {
    $("#myStats").innerHTML = `
      <div class="stat-card"><span class="eyebrow">${escapeHtml(uiText("workspace.statTasks", "查询任务"))}</span><strong>${tasks.length}</strong></div>
      <div class="stat-card"><span class="eyebrow">${escapeHtml(uiText("workspace.statCompleted", "已完成"))}</span><strong>${completed}</strong></div>
      <div class="stat-card"><span class="eyebrow">${escapeHtml(uiText("workspace.statPending", "待处理"))}</span><strong>${pending}</strong></div>
    `;
  }
  renderProfile();

  if (!$("#myTaskList")) return;

  if (!hasSupabaseSession()) {
    $("#myTaskList").innerHTML = `<div class="empty">${escapeHtml(uiText("workspace.supabaseMissing", "Supabase 还没配置，工作台先坐会儿。"))}</div>`;
    return;
  }
  if (!state.myPageLoaded) {
    $("#myTaskList").innerHTML = `<div class="empty">${escapeHtml(uiText("workspace.loading", "正在加载我的任务……"))}</div>`;
    return;
  }
  if (!tasks.length) {
    $("#myTaskList").innerHTML = `<div class="empty">${escapeHtml(uiText("workspace.empty", "还没有你的查询任务。先搜一个，小象才有班可上。"))}</div>`;
    return;
  }
  $("#myTaskList").innerHTML = tasks
    .map((task) => {
      const job = latestJob(task);
      const canRun = task.status !== "completed" && job?.status !== "running";
      return `
        <article class="task-card">
          <h3>${escapeHtml(titleFromQueryRow(task))}</h3>
          <p>
            <span class="pill">${escapeHtml(statusLabel(task))}</span>
            <span class="pill">${escapeHtml(displayPropertyText(task.asset_type))}</span>
            <span class="pill">${escapeHtml(`${task.year}年${task.month}月`)}</span>
          </p>
          <p>${escapeHtml(job?.current_step || task.markdown_title || uiText("workspace.savedQuery", "已保存查询记录"))}</p>
          <div class="task-actions">
            <button class="primary" type="button" data-run-query="${escapeHtml(task.id)}" ${canRun ? "" : "disabled"}>${escapeHtml(uiText("workspace.runJphouse", "手动执行 JPHOUSE"))}</button>
            <button type="button" data-view-query="${escapeHtml(task.query_key)}">${escapeHtml(uiText("workspace.viewResult", "查看结果"))}</button>
          </div>
        </article>
      `;
    })
    .join("");
  document.querySelectorAll("[data-run-query]").forEach((button) => {
    button.addEventListener("click", () => runJphouseFromMyPage(button.dataset.runQuery));
  });
  document.querySelectorAll("[data-view-query]").forEach((button) => {
    button.addEventListener("click", () => viewReportByQueryKey(button.dataset.viewQuery));
  });
}

function monthKey(text) {
  const match = String(text || "").match(/(\d{4})年(\d{1,2})月/);
  if (!match) return String(text || "未知月份");
  return `${match[1]}-${String(match[2]).padStart(2, "0")}`;
}

function numberFromText(text) {
  const cleaned = String(text || "").replace(/,/g, "");
  const match = cleaned.match(/([0-9]+(?:\.[0-9]+)?)/);
  return match ? Number(match[1]) : NaN;
}

function rowForLayout(rows, layout) {
  return (rows || []).find((row) => row.layout === layout) || null;
}

function ratioForLayout(record, layout) {
  const line = String(record.summary?.line || "");
  const part = line.split("｜").reduce((acc, item, index, arr) => {
    if (item === layout) return arr[index + 1] || "";
    return acc;
  }, "");
  return numberFromText(part);
}

function analysisValue(record, metric, layout) {
  if (metric === "rent") return numberFromText(rowForLayout(record.rental, layout)?.amount_jpy);
  if (metric === "sale") return numberFromText(rowForLayout(record.sale, layout)?.amount_jpy);
  return ratioForLayout(record, layout);
}

function analysisUnit(metric) {
  if (metric === "rent") return uiText("analysis.unitRent", "万日元/月");
  if (metric === "sale") return uiText("analysis.unitSale", "万日元");
  return "%";
}

function analysisMetricName(metric) {
  if (metric === "rent") return uiText("analysis.rent", "月租金");
  if (metric === "sale") return uiText("analysis.sale", "买房总价");
  return uiText("analysis.ratio", "租售比");
}

function formatAnalysisValue(value, metric) {
  if (!Number.isFinite(value)) return "暂无";
  return `${value.toFixed(metric === "ratio" ? 2 : 1)}${analysisUnit(metric)}`;
}

function allLayoutsForRecords(records) {
  const layouts = new Set();
  records.forEach((record) => {
    [...(record.rental || []), ...(record.sale || [])].forEach((row) => {
      if (row.layout) layouts.add(row.layout);
    });
  });
  const preferred = ["1LDK", "2LDK", "3LDK", "80㎡左右", "110㎡左右", "140㎡左右"];
  return [...preferred.filter((item) => layouts.has(item)), ...[...layouts].filter((item) => !preferred.includes(item)).sort()];
}

function compareCell(record, layout) {
  return {
    rent: formatAnalysisValue(analysisValue(record, "rent", layout), "rent"),
    sale: formatAnalysisValue(analysisValue(record, "sale", layout), "sale"),
    ratio: formatAnalysisValue(analysisValue(record, "ratio", layout), "ratio"),
  };
}

function compareOptionLabel(record) {
  return `${displayPropertyText(record.title)}｜${record.publish_month}`;
}

function syncCompareSelect(select, records, fallbackIndex) {
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">不选择</option>${records
    .map((record) => `<option value="${escapeHtml(record.id)}">${escapeHtml(compareOptionLabel(record))}</option>`)
    .join("")}`;
  if (records.some((record) => record.id === current)) {
    select.value = current;
  } else if (current === "" && select.dataset.ready) {
    select.value = "";
  } else if (records[fallbackIndex]) {
    select.value = records[fallbackIndex].id;
  }
  select.dataset.ready = "1";
}

function selectedCompareRecords(candidates) {
  const ids = ["#compareSelectA", "#compareSelectB", "#compareSelectC"].map((selector) => $(selector)?.value).filter(Boolean);
  const seen = new Set();
  return ids
    .filter((id) => {
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    })
    .map((id) => candidates.find((record) => record.id === id))
    .filter(Boolean);
}

function renderDimensions(selected) {
  const picker = $("#dimensionPicker");
  if (!picker) return [];
  const layouts = allLayoutsForRecords(selected);
  const checked = new Set([...picker.querySelectorAll("input:checked")].map((input) => input.value));
  const active = layouts.filter((layout) => checked.size ? checked.has(layout) : true);
  picker.innerHTML = layouts.length
    ? layouts
        .map((layout) => `
          <label class="dimension-chip">
            <input type="checkbox" value="${escapeHtml(layout)}" ${active.includes(layout) ? "checked" : ""} />
            <span>${escapeHtml(layout)}</span>
          </label>
        `)
        .join("")
    : `<div class="empty">${escapeHtml(uiText("analysis.noCompareSelection", "所选报告没有可比较维度。"))}</div>`;
  picker.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", renderAnalysis);
  });
  return active.length ? active : layouts;
}

function selectedCompareMetrics() {
  const checked = [...document.querySelectorAll("#metricPicker input:checked")].map((input) => input.value);
  return checked.length ? checked : ["rent", "sale", "ratio"];
}

function compareMetricLabel(metric) {
  if (metric === "rent") return uiText("analysis.rent", "租金");
  if (metric === "sale") return uiText("analysis.sale", "售价");
  return uiText("analysis.ratio", "租售比");
}

function renderCompare(matched) {
  if (!$("#compareSelectA") || !$("#compareTable")) return;
  const candidates = matched.slice(0, 30).map((item) => item.record);
  ["#compareSelectA", "#compareSelectB", "#compareSelectC"].forEach((selector, index) => {
    syncCompareSelect($(selector), candidates, index);
  });

  const selected = selectedCompareRecords(candidates);
  const layouts = renderDimensions(selected);
  const metrics = selectedCompareMetrics();
  if (!candidates.length) {
    $("#compareTable").innerHTML = `<div class="empty">${escapeHtml(uiText("analysis.noCompareData", "没有可比较的数据。先换个关键词。"))}</div>`;
    return;
  }
  if (!selected.length || !layouts.length) {
    $("#compareTable").innerHTML = `<div class="empty">${escapeHtml(uiText("analysis.noCompareSelection", "请选择要比较的数据和维度。"))}</div>`;
    return;
  }
  $("#compareTable").innerHTML = `
    <table class="compare-table">
      <thead>
        <tr>
          <th rowspan="2">维度</th>
          ${selected.map((record) => `<th colspan="${metrics.length}">${escapeHtml(displayPropertyText(record.title))}<small>${escapeHtml(record.publish_month)}</small></th>`).join("")}
        </tr>
        <tr>
          ${selected.map(() => metrics.map((metric) => `<th>${escapeHtml(compareMetricLabel(metric))}</th>`).join("")).join("")}
        </tr>
      </thead>
      <tbody>
        ${layouts
          .map((layout) => {
            const cells = selected
              .map((record) => {
                const values = compareCell(record, layout);
                return metrics.map((metric) => `<td>${escapeHtml(values[metric])}</td>`).join("");
              })
              .join("");
            return `
              <tr>
                <th>${escapeHtml(layout)}</th>
                ${cells}
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
}

function analysisLayouts() {
  const layouts = new Set();
  state.records.forEach((record) => {
    [...(record.rental || []), ...(record.sale || [])].forEach((row) => {
      if (row.layout) layouts.add(row.layout);
    });
  });
  const preferred = ["1LDK", "2LDK", "3LDK", "80㎡左右", "110㎡左右", "140㎡左右"];
  return [...preferred.filter((item) => layouts.has(item)), ...[...layouts].filter((item) => !preferred.includes(item)).sort()];
}

function drawAnalysisChart(points, metric) {
  const canvas = $("#analysisChart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#dedede";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = 28 + i * ((height - 72) / 4);
    ctx.beginPath();
    ctx.moveTo(44, y);
    ctx.lineTo(width - 18, y);
    ctx.stroke();
  }
  ctx.fillStyle = "#666";
  ctx.font = "13px sans-serif";
  if (!points.length) {
    ctx.fillText(uiText("analysis.noChart", "没有可画的数据。换个关键词或物件类型试试。"), 44, height / 2);
    return;
  }
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const xFor = (index) => 44 + index * ((width - 72) / Math.max(1, points.length - 1));
  const yFor = (value) => 28 + (1 - (value - min) / span) * (height - 72);
  ctx.strokeStyle = "#111";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = xFor(index);
    const y = yFor(point.value);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#111";
  points.forEach((point, index) => {
    const x = xFor(index);
    const y = yFor(point.value);
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillText(point.month.slice(5), x - 10, height - 18);
  });
  ctx.fillStyle = "#333";
  ctx.fillText(`${analysisMetricName(metric)}（${analysisUnit(metric)}）`, 44, 18);
  ctx.fillText(`${max.toFixed(1)}`, 6, yFor(max) + 4);
  ctx.fillText(`${min.toFixed(1)}`, 6, yFor(min) + 4);
}

function renderAnalysis() {
  const panel = $("#analysisPanel");
  if (!panel) return;
  panel.classList.toggle("hidden", !isLoggedIn());
  if (!isLoggedIn()) return;

  const layoutSelect = $("#analysisLayout");
  if (layoutSelect && !layoutSelect.dataset.ready) {
    layoutSelect.innerHTML = analysisLayouts().map((layout) => optionHtml(layout)).join("");
    layoutSelect.dataset.ready = "1";
  }

  const keyword = compact($("#analysisKeyword")?.value || "");
  const metric = $("#analysisMetric")?.value || "rent";
  const layout = $("#analysisLayout")?.value || analysisLayouts()[0] || "1LDK";
  const matched = state.records
    .filter((record) => !keyword || compact([record.title, record.publish_month, record.asset_type, (record.regions || []).join(""), record.markdown].join(" ")).includes(keyword))
    .map((record) => ({ record, value: analysisValue(record, metric, layout) }))
    .filter((item) => Number.isFinite(item.value));

  const byMonth = new Map();
  matched.forEach(({ record, value }) => {
    const key = monthKey(record.publish_month);
    const bucket = byMonth.get(key) || [];
    bucket.push(value);
    byMonth.set(key, bucket);
  });
  const points = [...byMonth.entries()]
    .map(([month, values]) => ({ month, value: values.reduce((sum, value) => sum + value, 0) / values.length }))
    .sort((a, b) => a.month.localeCompare(b.month));
  drawAnalysisChart(points, metric);

  $("#analysisHint").textContent = formatUiText("analysis.dynamicHint", `${analysisMetricName(metric)}｜${layout}｜匹配 ${matched.length} 条，月份点 ${points.length} 个。`, {
    metric: analysisMetricName(metric),
    layout,
    matched: matched.length,
    points: points.length,
  });
  renderCompare(matched);
  $("#analysisResults").innerHTML = matched
    .slice(0, 10)
    .map(({ record, value }) => `
      <article class="analysis-row">
        <div>
          <h3>${escapeHtml(displayPropertyText(record.title))}</h3>
          <p>${escapeHtml(record.publish_month)}｜${escapeHtml(displayPropertyText((record.regions || []).join(" / ") || record.asset_type || ""))}</p>
        </div>
        <strong>${escapeHtml(value.toFixed(metric === "ratio" ? 2 : 1))}${escapeHtml(analysisUnit(metric))}</strong>
      </article>
    `)
    .join("") || `<div class="empty">${escapeHtml(uiText("analysis.noMatched", "暂时没有匹配数据。换个关键词试试。"))}</div>`;
}

async function runJphouseFromMyPage(queryId) {
  const useAuthenticatedBackend = canUseAuthenticatedBackend();
  try {
    renderProgress(
      "云端 JPHOUSE",
      20,
      useAuthenticatedBackend
        ? ["发送任务到 FastAPI", "后台生成数据报告"]
        : ["发送任务到 Supabase Edge Function", "云端生成数据报告"],
    );
    let result = useAuthenticatedBackend
      ? await apiFetch(`/api/jobs/${encodeURIComponent(queryId)}/run`, { method: "POST" })
      : await supabaseFunctionFetch("jphouse-run", { query_id: queryId });
    if (useAuthenticatedBackend) {
      for (let i = 0; i < 30 && result?.status !== "completed"; i += 1) {
        if (result?.status === "failed") throw new Error(result.error_message || "生成失败");
        await delay(900);
        result = await apiFetch(`/api/jobs/${encodeURIComponent(queryId)}`);
        renderProgress("云端 JPHOUSE", result.progress || 20, [result.current_step || "生成中", `任务状态：${result.status}`]);
      }
      if (result?.status !== "completed") {
        if ($("#progressDialog").open) $("#progressDialog").close();
        setMessage("任务仍在运行，请稍后刷新工作台。", "info");
        await loadMyPage();
        render();
        return;
      }
    }
    if (result?.report) {
      const query = state.myTasks.find((item) => item.id === queryId);
      const record = supabaseReportToRecord(query ? optionsFromQueryRow(query) : {}, result.report);
      upsertRuntimeRecord(record);
    }
    renderProgress("云端 JPHOUSE", 100, ["任务完成", "报告已写入 Supabase"]);
    await delay(350);
    if ($("#progressDialog").open) $("#progressDialog").close();
    await loadMyPage();
    setMessage(useAuthenticatedBackend ? "JPHOUSE API 执行完成，可以查看结果。" : "JPHOUSE 云端执行完成，可以查看结果。", "success");
    render();
  } catch (error) {
    if ($("#progressDialog").open) $("#progressDialog").close();
    setMessage(
      useAuthenticatedBackend
        ? `JPHOUSE API 执行失败：${error.message}`
        : `云端执行失败：${error.message}。如果函数还没部署，先部署 jphouse-run。`,
      "error",
    );
    await loadMyPage();
    render();
  }
}

async function viewReportByQueryKey(key) {
  try {
    const report = canUseAuthenticatedBackend()
      ? await apiFetch(`/api/reports/${encodeURIComponent(key)}`)
      : (await supabaseUserFetch(`/property_reports?select=*&query_key=eq.${encodeURIComponent(key)}&limit=1`))?.[0];
    if (!report) {
      setMessage("这条还没有生成结果，先点手动执行 JPHOUSE。", "error");
      return;
    }
    const query = state.myTasks.find((item) => item.query_key === key);
    const record = supabaseReportToRecord(query ? optionsFromQueryRow(query) : {}, report);
    upsertRuntimeRecord(record);
    state.selectedId = record.id;
    renderView();
  } catch (error) {
    setMessage(`查看结果失败：${error.message}`, "error");
  }
}

function renderAccount() {
  const loggedIn = isLoggedIn();
  const registerMode = state.authMode === "register";
  const forgotMode = state.authMode === "forgot";
  $("#accountPanel")?.classList.toggle("compact-account", loggedIn);
  const profileName = state.profile?.display_name || state.session?.username;
  const taskCount = state.myTasks?.length || 0;
  const pendingCount = (state.myTasks || []).filter((task) => task.status !== "completed").length;
  const tier = state.profile?.membership_tier === "free" || !state.profile?.membership_tier ? uiText("account.freeTier", "免费版") : state.profile.membership_tier;
  const loggedOutTitle = uiText(
    $("#accountTitle")?.dataset.loggedOutKey,
    $("#accountTitle")?.dataset.loggedOutTitle || "登录后可以查询",
  );
  const loggedOutCopy = uiText(
    $("#accountCopy")?.dataset.loggedOutCopyKey,
    $("#accountCopy")?.dataset.loggedOutCopy || "未登录只能看最近 5 条数据。注册很简单，别紧张，不查户口。",
  );
  $("#accountTitle").textContent = loggedIn
    ? formatUiText("account.greeting", `你好，${profileName}`, { name: profileName })
    : forgotMode
      ? uiText("account.resetTitle", "找回密码")
      : loggedOutTitle;
  $("#accountCopy").textContent = loggedIn
    ? formatUiText("account.loggedIn", `${tier}｜任务 ${taskCount}｜待处理 ${pendingCount}｜${state.session.email}`, {
        tier,
        tasks: taskCount,
        pending: pendingCount,
        email: state.session.email,
      })
    : forgotMode
      ? uiText("account.resetCopy", "输入注册邮箱后，我们会发送找回密码邮件。如果没有收到，也不会暴露账户是否存在。")
      : loggedOutCopy;
  $("#accountTabs")?.classList.toggle("hidden", loggedIn || forgotMode);
  $("#forgotPasswordLink")?.classList.toggle("hidden", loggedIn || forgotMode);
  $("#loginForm")?.classList.toggle("hidden", loggedIn || registerMode || forgotMode);
  $("#registerForm")?.classList.toggle("hidden", loggedIn || !registerMode || forgotMode);
  $("#forgotPasswordForm")?.classList.toggle("hidden", loggedIn || !forgotMode);
  $("#logoutButton").classList.toggle("hidden", !loggedIn);
  document.querySelectorAll(".account-action-link").forEach((link) => {
    link.classList.toggle("hidden", !loggedIn);
  });
  ["prefectureSelect", "citySelect", "wardSelect", "assetTypeSelect", "yearSelect", "monthSelect", "queryButton"].forEach((id) => {
    const el = $(`#${id}`);
    if (el) el.disabled = !loggedIn;
  });
  const hint = $("#queryHint");
  if (hint) {
    hint.textContent = loggedIn
      ? uiText("query.hintLoggedIn", "选择条件后查询。已有数据直接展示；没有命中会保存到 Supabase，等 JPHOUSE 采集器补数据。")
      : uiText("query.hintLoggedOut", "登录后可以查询。已有记录直接调取，没做过的会进入生成流程。");
  }
}

function matchedRecords() {
  return state.records.filter(recordMatches);
}

function pageSize() {
  return isLoggedIn() ? 10 : 5;
}

function totalPages(records) {
  return Math.max(1, Math.ceil(records.length / pageSize()));
}

function renderLatest() {
  if (!$("#latestList")) return;
  const all = matchedRecords();
  const total = totalPages(all);
  if (state.page > total) state.page = total;
  const start = (state.page - 1) * pageSize();
  const records = all.slice(start, start + pageSize());

  const title = $("#latestTitle");
  if (title) {
    title.textContent = !isLoggedIn()
      ? uiText("latest.title", "最近更新内容")
      : state.queryOptions
        ? formatUiText("latest.searchResults", `查询结果：${queryTitle(state.queryOptions)}（${all.length}条）`, { title: queryTitle(state.queryOptions), count: all.length })
        : state.query
          ? formatUiText("latest.keywordResults", `搜索结果：${state.query}（${all.length}条）`, { query: state.query, count: all.length })
        : formatUiText("latest.allResults", `全部数据（${all.length}条）`, { count: all.length });
  }
  const eyebrow = $("#listEyebrow");
  if (eyebrow) eyebrow.textContent = isLoggedIn() ? uiText("latest.searchEyebrow", "Search results") : uiText("latest.eyebrow", "Latest updates");

  $("#pagination")?.classList.toggle("hidden", !isLoggedIn() || all.length <= pageSize());
  if ($("#pageInfo")) $("#pageInfo").textContent = formatUiText("latest.pageInfo", `第 ${state.page} / ${total} 页`, { page: state.page, total });
  if ($("#prevPage")) $("#prevPage").disabled = state.page <= 1;
  if ($("#nextPage")) $("#nextPage").disabled = state.page >= total;

  if (!records.length) {
    $("#latestList").innerHTML = `<div class="empty">${escapeHtml(uiText("latest.empty", "暂时没搜到。这个查询已经可以记录下来，等后端生成器接上。"))}</div>`;
    return;
  }

  $("#latestList").innerHTML = records
    .map((record) => {
      const regions = displayPropertyText((record.regions || []).join(" / ")) || "日本";
      return `
        <article class="latest-card" role="${isLoggedIn() ? "button" : "article"}" tabindex="${isLoggedIn() ? "0" : "-1"}" data-detail="${escapeHtml(record.id)}">
          <span class="latest-currency" aria-hidden="true">¥</span>
          <div>
            <h3>${escapeHtml(displayPropertyText(record.title))}</h3>
            <p class="latest-record-meta">${escapeHtml(formatUiText("latest.meta", `${record.publish_month} · ${regions}`, { month: record.publish_month, regions }))}</p>
          </div>
        </article>
      `;
    })
    .join("");
  document.querySelectorAll("[data-detail]").forEach((card) => {
    card.addEventListener("click", () => openDetail(card.dataset.detail));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDetail(card.dataset.detail);
      }
    });
  });
}

function renderQueryOptions() {
  const prefecture = $("#prefectureSelect");
  if (!prefecture) return;
  const city = $("#citySelect");
  const ward = $("#wardSelect");
  const assetType = $("#assetTypeSelect");
  const year = $("#yearSelect");
  const month = $("#monthSelect");
  if (!city || !ward || !assetType || !year || !month) return;
  const currentPrefecture = prefecture.value || "东京都";
  prefecture.innerHTML = `<option value="">${escapeHtml(uiText("query.select", "请选择"))}</option>${state.fieldOptions.prefectures.map((item) => optionHtml(item)).join("")}`;
  prefecture.value = state.fieldOptions.prefectures.includes(currentPrefecture) ? currentPrefecture : state.fieldOptions.prefectures[0] || "";
  const currentAssetType = assetType.value || "塔楼";
  assetType.innerHTML = state.fieldOptions.assetTypes.map((item) => optionHtml(item, assetTypeLabel(item))).join("");
  assetType.value = state.fieldOptions.assetTypes.includes(currentAssetType) ? currentAssetType : state.fieldOptions.assetTypes[0] || "";
  const currentYear = year.value || "2026";
  year.innerHTML = state.fieldOptions.years.map((item) => optionHtml(item)).join("");
  year.value = state.fieldOptions.years.includes(currentYear) ? currentYear : state.fieldOptions.years[0] || "";
  const currentMonth = month.value || "8";
  month.innerHTML = state.fieldOptions.months.map((item) => optionHtml(item, formatUiText("query.monthOption", `${item}月`, { month: item }))).join("");
  month.value = state.fieldOptions.months.includes(currentMonth) ? currentMonth : state.fieldOptions.months[0] || "";
  if (!prefecture.value) {
    prefecture.value = "东京都";
  }
  populateCities();
  populateWards();
}

function optionHtml(value, label = value) {
  return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
}

function assetTypeLabel(value) {
  const keys = {
    塔楼: "asset.tower",
    公寓: "asset.apartment",
    一户建: "asset.detached",
    其他物件: "asset.other",
  };
  return uiText(keys[value], displayPropertyText(value));
}

function populateCities() {
  const prefectureSelect = $("#prefectureSelect");
  const citySelect = $("#citySelect");
  if (!prefectureSelect || !citySelect) return;
  const prefecture = prefectureSelect.value;
  const currentCity = citySelect.value;
  const cities = state.fieldOptions.cities[prefecture] || [];
  citySelect.innerHTML = `<option value="">${escapeHtml(uiText("query.select", "请选择"))}</option>${cities.map((city) => optionHtml(city)).join("")}`;
  if (cities.includes(currentCity)) {
    citySelect.value = currentCity;
  } else if (cities.length) {
    citySelect.value = cities[0];
  }
}

function populateWards() {
  const prefectureSelect = $("#prefectureSelect");
  const citySelect = $("#citySelect");
  const wardSelect = $("#wardSelect");
  if (!prefectureSelect || !citySelect || !wardSelect) return;
  const prefecture = prefectureSelect.value;
  const city = citySelect.value;
  const currentWard = wardSelect.value;
  const wards = state.fieldOptions.wards[`${prefecture}::${city}`] || [];
  wardSelect.innerHTML = `<option value="">${escapeHtml(uiText("query.allWards", "全部区"))}</option>${wards.map((ward) => optionHtml(ward)).join("")}`;
  if (wards.includes(currentWard)) wardSelect.value = currentWard;
}

function readQueryOptions() {
  return {
    prefecture: $("#prefectureSelect").value,
    city: $("#citySelect").value,
    ward: $("#wardSelect").value,
    assetType: $("#assetTypeSelect").value,
    year: $("#yearSelect").value,
    month: $("#monthSelect").value,
  };
}

function saveQuery(options, status, matchedCount = 0) {
  const id = compact(queryTitle(options));
  const item = {
    id,
    title: queryTitle(options),
    options,
    status,
    matchedCount,
    markdownTitle: `# ${queryTitle(options)}`,
    xhsDraft: xhsDraftFromQuery(options),
    createdAt: new Date().toISOString(),
  };
  const history = getQueryHistory().filter((historyItem) => historyItem.id !== id);
  history.unshift(item);
  saveQueryHistory(history);
}

function renderQueryHistory() {
  const panel = $("#queryHistory");
  if (!panel) return;
  const historyList = $("#historyList");
  if (!historyList) return;
  const history = getQueryHistory();
  panel.classList.toggle("hidden", !isLoggedIn() || !history.length);
  historyList.innerHTML = history
    .slice(0, 5)
    .map(
      (item) => `
        <button class="history-chip" type="button" data-history="${escapeHtml(item.id)}">
          <span>${escapeHtml(item.title)}</span>
          <small>${escapeHtml(item.status)}${item.matchedCount ? ` · ${item.matchedCount}条` : ""}</small>
        </button>
      `,
    )
    .join("");
  document.querySelectorAll("[data-history]").forEach((button) => {
    button.addEventListener("click", () => {
      const item = getQueryHistory().find((historyItem) => historyItem.id === button.dataset.history);
      if (!item) return;
      applyOptionsToForm(item.options);
      state.queryOptions = item.options;
      state.query = "";
      state.page = 1;
      state.selectedId = "";
      render();
    });
  });
}

function applyOptionsToForm(options) {
  $("#prefectureSelect").value = options.prefecture || "";
  populateCities();
  $("#citySelect").value = options.city || "";
  populateWards();
  $("#wardSelect").value = options.ward || "";
  $("#assetTypeSelect").value = options.assetType || "塔楼";
  $("#yearSelect").value = options.year || "2026";
  $("#monthSelect").value = options.month || "8";
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function showProgress(title, matchedCount) {
  const steps = [
    "组合查询条件，生成 Markdown 标题",
    "检查历史查询记录",
    matchedCount ? "命中已有数据，直接调取" : "未命中本地数据，准备备用数据源",
    matchedCount ? "整理数据浏览页" : "保存待生成记录，等待 JPHOUSE 采集器接入",
  ];
  $("#progressTitle").textContent = title;
  $("#progressSteps").innerHTML = steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("");
  $("#progressBar").style.width = "8%";
  $("#progressDialog").showModal();
  for (let i = 0; i < steps.length; i += 1) {
    $("#progressBar").style.width = `${Math.round(((i + 1) / steps.length) * 100)}%`;
    await delay(260);
  }
  await delay(220);
  $("#progressDialog").close();
}

function renderProgress(title, progress, steps) {
  $("#progressTitle").textContent = title;
  $("#progressBar").style.width = `${Math.max(5, Math.min(100, progress))}%`;
  $("#progressSteps").innerHTML = steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("");
  if (!$("#progressDialog").open) $("#progressDialog").showModal();
}

async function runBackendQuery(options) {
  const title = queryTitle(options);
  renderProgress(title, 8, ["发送查询条件到后端", "检查 PostgreSQL 历史索引"]);
  const payload = {
    prefecture: options.prefecture,
    city: options.city,
    ward: options.ward || "",
    asset_type: options.assetType,
    year: Number(options.year),
    month: Number(options.month),
    username: state.session?.username || "",
  };
  const created = await apiFetch("/api/query", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (created.report) {
    const record = backendReportToRecord(options, created.report);
    upsertRuntimeRecord(record);
    renderProgress(title, 100, ["命中 PostgreSQL 历史数据", "返回数据浏览页面"]);
    await delay(280);
    $("#progressDialog").close();
    return { matchedCount: 1, status: created.cached ? "已调取" : "已生成" };
  }
  if (!created.job_id) {
    $("#progressDialog").close();
    return { matchedCount: 0, status: "待生成" };
  }
  for (let i = 0; i < 30; i += 1) {
    await delay(900);
    const job = await apiFetch(`/api/jobs/${created.job_id}`);
    renderProgress(title, job.progress || 20, [job.current_step || "生成中", `任务状态：${job.status}`]);
    if (job.status === "completed" && job.report) {
      const record = backendReportToRecord(options, job.report);
      upsertRuntimeRecord(record);
      await delay(250);
      $("#progressDialog").close();
      return { matchedCount: 1, status: "已生成" };
    }
    if (job.status === "failed") throw new Error(job.error_message || "生成失败");
  }
  $("#progressDialog").close();
  return { matchedCount: 0, status: "生成中" };
}

async function handleStructuredQuery(event) {
  event.preventDefault();
  if (!isLoggedIn()) return;
  const options = readQueryOptions();
  if (!options.prefecture || !options.city) {
    setMessage(uiText("query.citiesRequired", "都道府县和市至少选一下，不然小象不知道往哪儿跑。"), "error");
    return;
  }
  let matchedCount = state.records.filter((record) => recordMatchesOptions(record, options)).length;
  let status = matchedCount ? "已调取" : "待生成";
  if (canUseAuthenticatedBackend()) {
    try {
      const backendResult = await runBackendQuery(options);
      matchedCount = backendResult.matchedCount || matchedCount;
      status = backendResult.status;
    } catch (error) {
      if ($("#progressDialog").open) $("#progressDialog").close();
      setMessage(`后端查询失败，先显示本地缓存：${error.message}`, "error");
      await showProgress(queryTitle(options), matchedCount);
    }
  } else {
    setMessage(uiText("query.backendFallback", "后端尚未配置，当前只显示本地公开数据；登录后的项目查询需要连接 API。"), "error");
    await showProgress(queryTitle(options), matchedCount);
  }
  saveQuery(options, status, matchedCount);
  state.queryOptions = options;
  state.query = "";
  state.page = 1;
  state.selectedId = "";
  setMessage(
    matchedCount
      ? formatUiText("query.matched", `查到了 ${matchedCount} 条，直接调取。`, { count: matchedCount })
      : uiText("query.noLocal", "当前库里还没有，已保存查询记录，等 JPHOUSE 采集器补数据。"),
    matchedCount ? "success" : "",
  );
  render();
}

function render() {
  renderAccount();
  renderQueryOptions();
  renderQueryHistory();
  renderMyPage();
  renderAnalysis();
  renderView();
}

function renderView() {
  const detail = isLoggedIn() && state.selectedId;
  $("#detailPage")?.classList.toggle("hidden", !detail);
  $(".latest-panel")?.classList.toggle("hidden", detail);
  $(".query-panel")?.classList.toggle("hidden", detail);
  $("#mypagePanel")?.classList.toggle("hidden", detail || !isLoggedIn());
  if (detail) {
    renderDetail();
    return;
  }
  renderLatest();
}

function showMode(mode) {
  const registerMode = mode === "register";
  state.authMode = mode === "forgot" ? "forgot" : registerMode ? "register" : "login";
  $("#showLogin").classList.toggle("active", !registerMode);
  $("#showRegister").classList.toggle("active", registerMode);
  setMessage("");
  renderAccount();
}

async function requestPasswordReset(event) {
  event.preventDefault();
  const email = $("#forgotPasswordEmail")?.value.trim();
  const submitButton = $("#forgotPasswordForm button[type='submit']");
  if (!email) {
    setMessage("请输入注册邮箱。", "error");
    return;
  }
  if (!hasSupabase()) {
    setMessage("账户服务还未配置，暂时无法发送找回邮件；没有修改任何账户。", "error");
    return;
  }
  try {
    submitButton.disabled = true;
    setMessage("正在发送找回邮件……");
    await supabaseAuthFetch(`/recover?redirect_to=${encodeURIComponent(appRedirectUrl())}`, {
      method: "POST",
      body: JSON.stringify({ email }),
    });
    $("#forgotPasswordForm").reset();
    setMessage("如果这个邮箱已注册，找回密码邮件会发到邮箱；请检查收件箱和垃圾邮件。", "success");
  } catch {
    setMessage("找回密码请求未完成，请稍后再试。", "error");
  } finally {
    submitButton.disabled = false;
  }
}

async function register(event) {
  event.preventDefault();
  const username = $("#registerUsername").value.trim();
  const email = $("#registerEmail").value.trim();
  const password = $("#registerPassword").value;
  const submitButton = $("#registerForm button[type='submit']");

  if (!username || !email || !password) {
    setMessage("用户名、邮件、密码都要填。小象不挑食，但不能空盘。", "error");
    return;
  }
  if (!passwordIsValid(password)) {
    setMessage("密码需为 12–128 位，且不能包含控制字符。", "error");
    return;
  }

  if (!hasSupabase()) {
    setMessage("账户服务还未配置，暂时无法注册；没有保存密码。", "error");
    return;
  }
  const consent = readRegistrationConsent();
  if (!consent) return;

  try {
    submitButton.disabled = true;
    setMessage("正在注册，小象在 Supabase 门口排队……");
    const data = await supabaseAuthFetch(`/signup?redirect_to=${encodeURIComponent(appRedirectUrl())}`, {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        data: {
          username,
          consent_version: consent.consentVersion,
          consent_at: consent.consentAt,
          terms_version: consent.termsVersion,
          consent_source: "registration",
        },
      }),
    });
    const session = sessionFromAuth(data, { username, email });
    $("#registerForm").reset();
    state.query = "";
    state.queryOptions = null;
    state.page = 1;
    state.selectedId = "";
    if (data?.access_token) {
      saveSession(session);
      await ensureUserProfile();
      await loadMyPage();
      setMessage("注册成功，已登录。可以搜房了，钱包先深呼吸。", "success");
    } else {
      setMessage("注册成功，但后台还开着邮箱确认。请完成邮箱确认后再登录。", "success");
    }
    render();
  } catch {
    setMessage("注册未完成，请稍后再试。", "error");
  } finally {
    submitButton.disabled = false;
  }
}

async function login(event) {
  event.preventDefault();
  const email = $("#loginUsername").value.trim();
  const password = $("#loginPassword").value;
  const submitButton = $("#loginForm button[type='submit']");

  if (!email || !password) {
    setMessage("邮件和密码都要填。", "error");
    return;
  }

  if (!hasSupabase()) {
    setMessage("账户服务还未配置，暂时无法登录；没有读取本地密码。", "error");
    return;
  }

  try {
    submitButton.disabled = true;
    setMessage("正在登录，小象在翻钥匙串……");
    const data = await supabaseAuthFetch("/token?grant_type=password", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    const session = sessionFromAuth(data, { email });
    saveSession(session);
    await ensureUserProfile();
    await loadMyPage();
    $("#loginForm").reset();
    state.page = 1;
    state.selectedId = "";
    state.queryOptions = null;
    setMessage("登录成功，可以搜了。", "success");
    render();
  } catch {
    setMessage("邮箱或密码不正确，或账户暂不可用。", "error");
  } finally {
    submitButton.disabled = false;
  }
}

async function logout() {
  const accessToken = state.session?.accessToken;
  if (hasSupabase() && accessToken) {
    try {
      await supabaseAuthFetch("/logout", {
        method: "POST",
        authToken: accessToken,
      });
    } catch {
      // Local logout should still complete even if the remote token already expired.
    }
  }
  state.query = "";
  state.queryOptions = null;
  state.page = 1;
  state.selectedId = "";
  state.myTasks = [];
  state.myPageLoaded = false;
  state.profile = null;
  state.profileLoaded = false;
  state.profileEditing = false;
  state.authMode = "login";
  saveSession(null);
  setMessage("已退出。搜索框又开始装睡了。");
  render();
}

function renderDetail() {
  if (!$("#detailContent")) return;
  const record = state.records.find((item) => item.id === state.selectedId);
  if (!record) {
    state.selectedId = "";
    render();
    return;
  }
  const rental = record.rental || [];
  const sale = record.sale || [];
  $("#detailContent").innerHTML = `
    <article class="detail-card">
      <h2>${escapeHtml(displayPropertyText(record.title))}</h2>
      <p class="meta">
        <span class="pill">${escapeHtml(record.publish_month)}</span>
        <span class="pill">${escapeHtml((record.regions || []).join(" / "))}</span>
        <span class="pill">${escapeHtml((record.layouts || []).join(" / "))}</span>
      </p>
      <div class="detail-images">
        ${(record.images || [])
          .map(
            (src, index) => `
              <button class="image-zoom" type="button" data-image="${escapeHtml(src)}" aria-label="放大第 ${index + 1} 张图片">
                <img src="${escapeHtml(src)}" alt="${escapeHtml(displayPropertyText(record.title))} 配图 ${index + 1}" />
              </button>
            `,
          )
          .join("")}
      </div>
      <div class="detail-grid">
        <section>
          <h3>租房子</h3>
          ${rental.map((row) => `<p><b>${escapeHtml(row.layout)}</b>｜${escapeHtml(rowLine(row))}</p>`).join("")}
        </section>
        <section>
          <h3>买房子</h3>
          ${sale.map((row) => `<p><b>${escapeHtml(row.layout)}</b>｜${escapeHtml(rowLine(row))}</p>`).join("")}
        </section>
      </div>
      <pre>${escapeHtml(displayMarkdown(record.markdown))}</pre>
    </article>
  `;
  document.querySelectorAll("[data-image]").forEach((button) => {
    button.addEventListener("click", () => openImage(button.dataset.image));
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openDetail(id) {
  if (!isLoggedIn()) return;
  state.selectedId = id;
  renderView();
}

function closeDetail() {
  state.selectedId = "";
  renderView();
}

function openImage(src) {
  if (!$("#largeImage") || !$("#imageDialog")) return;
  $("#largeImage").src = src;
  $("#imageDialog").showModal();
}

function closeImage() {
  if (!$("#largeImage") || !$("#imageDialog")) return;
  $("#imageDialog").close();
  $("#largeImage").removeAttribute("src");
}

async function init() {
  try {
    const response = await fetch("content-library.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`content-library.json ${response.status}`);
    state.records = await response.json();
  } catch {
    // Generated content is optional for account/privacy controls and may be absent in a clean checkout.
    state.records = [];
  }
  await loadFieldOptions();
  await handleAuthRedirect();
  await refreshSupabaseSession();
  await loadRemoteReports();
  try {
    await ensureUserProfile();
  } catch {
    state.profile = null;
    state.profileLoaded = true;
  }
  try {
    await loadMyPage();
  } catch {
    state.myTasks = [];
    state.myPageLoaded = true;
  }
  on("#showLogin", "click", () => showMode("login"));
  on("#showRegister", "click", () => showMode("register"));
  on("#forgotPasswordLink", "click", (event) => {
    event.preventDefault();
    showMode("forgot");
  });
  on("#registerForm", "submit", register);
  on("#loginForm", "submit", login);
  on("#forgotPasswordForm", "submit", requestPasswordReset);
  on("#logoutButton", "click", logout);
  on("#prefectureSelect", "change", () => {
    populateCities();
    populateWards();
  });
  on("#citySelect", "change", populateWards);
  on("#queryForm", "submit", handleStructuredQuery);
  on("#backToList", "click", closeDetail);
  on("#refreshMyPage", "click", async () => {
    state.myPageLoaded = false;
    state.profileLoaded = false;
    renderMyPage();
    await ensureUserProfile();
    await loadMyPage();
    render();
    setMessage("工作台已刷新。小象打卡成功。", "success");
  });
  on("#editProfileButton", "click", () => {
    state.profileEditing = !state.profileEditing;
    renderProfile();
  });
  on("#cancelProfileButton", "click", () => {
    state.profileEditing = false;
    renderProfile();
  });
  on("#profileForm", "submit", saveProfile);
  on("#passwordForm", "submit", updatePassword);
  on("#openDeleteAccountButton", "click", () => $("#deleteAccountDialog")?.showModal());
  on("#deleteAccountDialog", "close", () => {
    const confirmation = $("#deleteAccountConfirm");
    if (confirmation) confirmation.checked = false;
  });
  on("#confirmDeleteAccountButton", "click", requestAccountDeletion);
  on("#analysisForm", "submit", (event) => {
    event.preventDefault();
    renderAnalysis();
  });
  on("#analysisMetric", "change", renderAnalysis);
  on("#analysisLayout", "change", renderAnalysis);
  on("#compareSelectA", "change", renderAnalysis);
  on("#compareSelectB", "change", renderAnalysis);
  on("#compareSelectC", "change", renderAnalysis);
  document.querySelectorAll("#metricPicker input").forEach((input) => {
    input.addEventListener("change", renderAnalysis);
  });
  on("#closeImage", "click", closeImage);
  on("#imageDialog", "click", (event) => {
    if (event.target.id === "imageDialog") closeImage();
  });
  on("#prevPage", "click", () => {
    state.page = Math.max(1, state.page - 1);
    renderLatest();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  on("#nextPage", "click", () => {
    state.page += 1;
    renderLatest();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  if ($("#prefectureSelect")) {
    populateCities();
    populateWards();
  }
  document.body.classList.remove("auth-pending");
  document.body.classList.add("auth-ready");
  render();
}

init().catch((error) => {
  document.body.classList.remove("auth-pending");
  document.body.classList.add("auth-ready");
  const target = $("#latestList") || $("#myTaskList");
  if (target) target.innerHTML = `<div class="empty">数据加载失败：${escapeHtml(error.message)}</div>`;
});

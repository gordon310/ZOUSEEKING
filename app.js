const USERS_KEY = "zou_house_users";
const SESSION_KEY = "zou_house_session";
const QUERY_HISTORY_KEY = "zou_house_query_history";
const API_BASE_URL = (window.ZOUSEEKING_API_BASE_URL || localStorage.getItem("zou_house_api_base") || "").replace(/\/$/, "");
const SUPABASE_URL = (window.ZOUSEEKING_SUPABASE_URL || localStorage.getItem("zou_house_supabase_url") || "").replace(/\/$/, "");
const SUPABASE_ANON_KEY = window.ZOUSEEKING_SUPABASE_ANON_KEY || localStorage.getItem("zou_house_supabase_anon_key") || "";

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
};

const $ = (selector) => document.querySelector(selector);

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

function getUsers() {
  return readJson(USERS_KEY, []);
}

function saveUsers(users) {
  localStorage.setItem(USERS_KEY, JSON.stringify(users));
}

function getQueryHistory() {
  return readJson(QUERY_HISTORY_KEY, []);
}

function saveQueryHistory(items) {
  localStorage.setItem(QUERY_HISTORY_KEY, JSON.stringify(items.slice(0, 30)));
}

async function passwordHash(password) {
  const data = new TextEncoder().encode(password);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function isLoggedIn() {
  return Boolean(state.session?.username);
}

function setMessage(text, tone = "") {
  $("#formMessage").textContent = text;
  $("#formMessage").className = `form-message ${tone}`;
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

function queryTitle(options) {
  const area = [options.prefecture, options.city, options.ward].filter(Boolean).join("");
  return `${area || "日本"}${options.assetType}｜${options.year}年${Number(options.month)}月`;
}

function queryKey(options) {
  return [options.prefecture, options.city, options.ward || "全部区", options.assetType, options.year, Number(options.month)].join("::");
}

function xhsDraftFromQuery(options) {
  const title = queryTitle(options);
  return `# ${title}\n\n## 小红书发布内容\n${title}，租还是买？\n\n数据生成中。已有相同查询会直接调取历史数据；没有的话，JPHOUSE 会按备用数据源抓取租房子、买房子、房型面积、日元/RMB、总而言之。`;
}

function hasBackend() {
  return Boolean(API_BASE_URL);
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
    setMessage(`邮箱确认失败：${decodeURIComponent(error)}`, "error");
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
  } catch (authError) {
    history.replaceState(null, "", appRedirectUrl());
    setMessage(`邮箱确认成功但登录状态读取失败：${authError.message}`, "error");
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

function rowLine(row) {
  const amount = [row.amount_jpy, row.amount_rmb].filter(Boolean).join(" / ");
  const unit = [row.unit_jpy, row.unit_rmb].filter(Boolean).join(" / ");
  return `${row.area}｜${amount}｜${unit}`;
}

function displayMarkdown(markdown) {
  return String(markdown || "")
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
}

function previewText(record) {
  const rental = record.rental?.[0];
  const sale = record.sale?.[0];
  const rent = rental ? `${rental.layout} 租 ${rental.amount_jpy} / ${rental.amount_rmb}` : "暂无租赁数据";
  const buy = sale ? `${sale.layout} 买 ${sale.amount_jpy} / ${sale.amount_rmb}` : "暂无买卖数据";
  return `${rent}；${buy}`;
}

function renderAccount() {
  const loggedIn = isLoggedIn();
  $("#accountTitle").textContent = loggedIn ? `你好，${state.session.username}` : "登录后可以查询";
  $("#accountCopy").textContent = loggedIn
    ? `邮箱：${state.session.email}。JPHOUSE 查询已打开，钱包请自行保重。`
    : "未登录只能看最近 5 条数据。注册很简单，别紧张，不查户口。";
  $("#accountTabs").classList.toggle("hidden", loggedIn);
  $("#loginForm").classList.toggle("hidden", loggedIn || $("#showRegister").classList.contains("active"));
  $("#registerForm").classList.toggle("hidden", loggedIn || $("#showLogin").classList.contains("active"));
  $("#logoutButton").classList.toggle("hidden", !loggedIn);
  ["prefectureSelect", "citySelect", "wardSelect", "assetTypeSelect", "yearSelect", "monthSelect", "queryButton"].forEach((id) => {
    const el = $(`#${id}`);
    if (el) el.disabled = !loggedIn;
  });
  const hint = $("#queryHint");
  if (hint) {
    hint.textContent = loggedIn
      ? "选择条件后查询。已有数据直接展示；没有命中会保存到 Supabase，等 JPHOUSE 采集器补数据。"
      : "登录后可以查询。已有记录直接调取，没做过的会进入生成流程。";
  }
}

function matchedRecords() {
  return state.records.filter(recordMatches);
}

function pageSize() {
  return isLoggedIn() ? 20 : 5;
}

function totalPages(records) {
  return Math.max(1, Math.ceil(records.length / pageSize()));
}

function renderLatest() {
  const all = matchedRecords();
  const total = totalPages(all);
  if (state.page > total) state.page = total;
  const start = (state.page - 1) * pageSize();
  const records = all.slice(start, start + pageSize());

  $("#latestTitle").textContent = !isLoggedIn()
    ? "最近发布的数据"
    : state.queryOptions
      ? `查询结果：${queryTitle(state.queryOptions)}（${all.length}条）`
      : state.query
        ? `搜索结果：${state.query}（${all.length}条）`
      : `全部数据（${all.length}条）`;
  $("#listEyebrow").textContent = isLoggedIn() ? "Search Results" : "Latest 5";

  $("#pagination").classList.toggle("hidden", !isLoggedIn() || all.length <= pageSize());
  $("#pageInfo").textContent = `第 ${state.page} / ${total} 页`;
  $("#prevPage").disabled = state.page <= 1;
  $("#nextPage").disabled = state.page >= total;

  if (!records.length) {
    $("#latestList").innerHTML = `<div class="empty">暂时没搜到。这个查询已经可以记录下来，等后端生成器接上，小象就能现场抓数。</div>`;
    return;
  }

  $("#latestList").innerHTML = records
    .map((record) => {
      const cover = record.images?.[0] || "";
      return `
        <article class="latest-card" role="${isLoggedIn() ? "button" : "article"}" tabindex="${isLoggedIn() ? "0" : "-1"}" data-detail="${escapeHtml(record.id)}">
          <img src="${cover}" alt="${escapeHtml(record.title)} 封面" />
          <div>
            <h3>${escapeHtml(record.title)}</h3>
            <p class="meta">
              <span class="pill">${escapeHtml(record.publish_month)}</span>
              <span class="pill">${escapeHtml((record.regions || []).join(" / "))}</span>
              <span class="pill">${escapeHtml((record.layouts || []).join(" / "))}</span>
            </p>
            <p>${escapeHtml(previewText(record))}</p>
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
  const currentPrefecture = prefecture.value || "东京都";
  prefecture.innerHTML = `<option value="">请选择</option>${state.fieldOptions.prefectures.map((item) => optionHtml(item)).join("")}`;
  prefecture.value = state.fieldOptions.prefectures.includes(currentPrefecture) ? currentPrefecture : state.fieldOptions.prefectures[0] || "";
  const currentAssetType = $("#assetTypeSelect").value || "塔楼";
  $("#assetTypeSelect").innerHTML = state.fieldOptions.assetTypes.map((item) => optionHtml(item)).join("");
  $("#assetTypeSelect").value = state.fieldOptions.assetTypes.includes(currentAssetType) ? currentAssetType : state.fieldOptions.assetTypes[0] || "";
  const currentYear = $("#yearSelect").value || "2026";
  $("#yearSelect").innerHTML = state.fieldOptions.years.map((item) => optionHtml(item)).join("");
  $("#yearSelect").value = state.fieldOptions.years.includes(currentYear) ? currentYear : state.fieldOptions.years[0] || "";
  const currentMonth = $("#monthSelect").value || "8";
  $("#monthSelect").innerHTML = state.fieldOptions.months.map((item) => optionHtml(item, `${item}月`)).join("");
  $("#monthSelect").value = state.fieldOptions.months.includes(currentMonth) ? currentMonth : state.fieldOptions.months[0] || "";
  if (!prefecture.value) {
    prefecture.value = "东京都";
  }
  populateCities();
  populateWards();
}

function optionHtml(value, label = value) {
  return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
}

function populateCities() {
  const prefecture = $("#prefectureSelect").value;
  const currentCity = $("#citySelect").value;
  const cities = state.fieldOptions.cities[prefecture] || [];
  $("#citySelect").innerHTML = `<option value="">请选择</option>${cities.map((city) => optionHtml(city)).join("")}`;
  if (cities.includes(currentCity)) {
    $("#citySelect").value = currentCity;
  } else if (cities.length) {
    $("#citySelect").value = cities[0];
  }
}

function populateWards() {
  const prefecture = $("#prefectureSelect").value;
  const city = $("#citySelect").value;
  const currentWard = $("#wardSelect").value;
  const wards = state.fieldOptions.wards[`${prefecture}::${city}`] || [];
  $("#wardSelect").innerHTML = `<option value="">全部区</option>${wards.map((ward) => optionHtml(ward)).join("")}`;
  if (wards.includes(currentWard)) $("#wardSelect").value = currentWard;
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
  const history = getQueryHistory();
  panel.classList.toggle("hidden", !isLoggedIn() || !history.length);
  $("#historyList").innerHTML = history
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

async function runSupabaseQuery(options) {
  const title = queryTitle(options);
  const key = queryKey(options);
  renderProgress(title, 8, ["连接 Supabase", "检查 PostgreSQL 历史索引"]);
  const existing = await supabaseFetch(`/property_reports?select=*&query_key=eq.${encodeURIComponent(key)}&limit=1`);
  if (existing?.[0]) {
    const record = supabaseReportToRecord(options, existing[0]);
    upsertRuntimeRecord(record);
    renderProgress(title, 100, ["命中 Supabase 历史数据", "返回数据浏览页面"]);
    await delay(280);
    $("#progressDialog").close();
    return { matchedCount: 1, status: "已调取" };
  }

  renderProgress(title, 42, ["未命中历史数据", "保存查询索引"]);
  const queryRows = await supabaseFetch("/queries?on_conflict=query_key", {
    method: "POST",
    headers: { Prefer: "resolution=merge-duplicates,return=representation" },
    body: JSON.stringify({
      query_key: key,
      prefecture: options.prefecture,
      city: options.city,
      ward: options.ward || "",
      asset_type: options.assetType,
      year: Number(options.year),
      month: Number(options.month),
      status: "pending",
      markdown_title: `# ${title}`,
      xhs_draft: xhsDraftFromQuery(options),
      requested_by_name: state.session?.username || "",
      requested_by_email: state.session?.email || "",
    }),
  });
  const queryId = queryRows?.[0]?.id;
  if (queryId) {
    await supabaseFetch("/generation_jobs", {
      method: "POST",
      body: JSON.stringify({
        query_id: queryId,
        status: "pending",
        progress: 5,
        current_step: "已保存查询，等待 JPHOUSE 采集器生成",
      }),
    });
  }
  renderProgress(title, 100, ["已保存查询记录", "等待本地/后端生成器补数据"]);
  await delay(280);
  $("#progressDialog").close();
  return { matchedCount: 0, status: "已入库待生成" };
}

async function handleStructuredQuery(event) {
  event.preventDefault();
  if (!isLoggedIn()) return;
  const options = readQueryOptions();
  if (!options.prefecture || !options.city) {
    setMessage("都道府县和市至少选一下，不然小象不知道往哪儿跑。", "error");
    return;
  }
  let matchedCount = state.records.filter((record) => recordMatchesOptions(record, options)).length;
  let status = matchedCount ? "已调取" : "待生成";
  if (hasSupabase()) {
    try {
      const supabaseResult = await runSupabaseQuery(options);
      matchedCount = supabaseResult.matchedCount || matchedCount;
      status = supabaseResult.status;
    } catch (error) {
      if ($("#progressDialog").open) $("#progressDialog").close();
      setMessage(`Supabase 查询失败，先显示本地缓存：${error.message}`, "error");
      await showProgress(queryTitle(options), matchedCount);
    }
  } else if (hasBackend()) {
    try {
      const backendResult = await runBackendQuery(options);
      matchedCount = backendResult.matchedCount;
      status = backendResult.status;
    } catch (error) {
      if ($("#progressDialog").open) $("#progressDialog").close();
      setMessage(`后端查询失败，先显示本地缓存：${error.message}`, "error");
      await showProgress(queryTitle(options), matchedCount);
    }
  } else {
    await showProgress(queryTitle(options), matchedCount);
  }
  saveQuery(options, status, matchedCount);
  state.queryOptions = options;
  state.query = "";
  state.page = 1;
  state.selectedId = "";
  setMessage(
    matchedCount ? `查到了 ${matchedCount} 条，直接调取。` : "当前库里还没有，已保存查询记录，等 JPHOUSE 采集器补数据。",
    matchedCount ? "success" : "",
  );
  render();
}

function render() {
  renderAccount();
  renderQueryOptions();
  renderQueryHistory();
  renderView();
}

function renderView() {
  const detail = isLoggedIn() && state.selectedId;
  $("#detailPage").classList.toggle("hidden", !detail);
  $(".latest-panel").classList.toggle("hidden", detail);
  $(".query-panel").classList.toggle("hidden", detail);
  if (detail) {
    renderDetail();
    return;
  }
  renderLatest();
}

function showMode(mode) {
  const registerMode = mode === "register";
  $("#showLogin").classList.toggle("active", !registerMode);
  $("#showRegister").classList.toggle("active", registerMode);
  setMessage("");
  renderAccount();
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
  if (password.length < 6) {
    setMessage("密码至少 6 位，太短了会被生活教育。", "error");
    return;
  }

  if (hasSupabase()) {
    try {
      submitButton.disabled = true;
      setMessage("正在注册，小象在 Supabase 门口排队……");
      const data = await supabaseAuthFetch(`/signup?redirect_to=${encodeURIComponent(appRedirectUrl())}`, {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          data: { username },
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
        setMessage("注册成功，已登录。可以搜房了，钱包先深呼吸。", "success");
      } else {
        setMessage("注册成功，但后台还开着邮箱确认。请在 Supabase 关闭 Confirm email，然后用邮箱密码登录。", "success");
      }
      render();
      return;
    } catch (error) {
      const message = String(error.message || "");
      setMessage(`注册失败：${message}`, "error");
      return;
    } finally {
      submitButton.disabled = false;
    }
  }

  const users = getUsers();
  if (users.some((user) => compact(user.username) === compact(username))) {
    setMessage("这个用户名已经注册过了。换个马甲试试。", "error");
    return;
  }

  const user = {
    username,
    email,
    passwordHash: await passwordHash(password),
    createdAt: new Date().toISOString(),
  };
  users.push(user);
  saveUsers(users);
  saveSession({ username, email, provider: "local" });
  $("#registerForm").reset();
  state.query = "";
  state.queryOptions = null;
  state.page = 1;
  state.selectedId = "";
  setMessage("注册成功，查询门打开了。", "success");
  render();
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

  if (hasSupabase()) {
    try {
      submitButton.disabled = true;
      setMessage("正在登录，小象在翻钥匙串……");
      const data = await supabaseAuthFetch("/token?grant_type=password", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      const session = sessionFromAuth(data, { email });
      saveSession(session);
      $("#loginForm").reset();
      state.page = 1;
      state.selectedId = "";
      state.queryOptions = null;
      setMessage("登录成功，可以搜了。", "success");
      render();
      return;
    } catch (error) {
      const message = String(error.message || "");
      if (message.includes("Invalid login credentials")) {
        setMessage("邮箱或密码不对。别慌，人生经常这样。", "error");
      } else if (message.includes("Email not confirmed")) {
        setMessage("后台还开着邮箱确认。请在 Supabase 关闭 Confirm email 后再登录。", "error");
      } else {
        setMessage(`登录失败：${message}`, "error");
      }
      return;
    } finally {
      submitButton.disabled = false;
    }
  }

  const user = getUsers().find((item) => compact(item.email) === compact(email) || compact(item.username) === compact(email));

  if (!user || user.passwordHash !== (await passwordHash(password))) {
    setMessage("用户名或密码不对。别慌，人生经常这样。", "error");
    return;
  }

  saveSession({ username: user.username, email: user.email, provider: "local" });
  $("#loginForm").reset();
  state.page = 1;
  state.selectedId = "";
  state.queryOptions = null;
  setMessage("登录成功，可以搜了。", "success");
  render();
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
  saveSession(null);
  setMessage("已退出。搜索框又开始装睡了。");
  render();
}

function renderDetail() {
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
      <h2>${escapeHtml(record.title)}</h2>
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
                <img src="${escapeHtml(src)}" alt="${escapeHtml(record.title)} 配图 ${index + 1}" />
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
  $("#largeImage").src = src;
  $("#imageDialog").showModal();
}

function closeImage() {
  $("#imageDialog").close();
  $("#largeImage").removeAttribute("src");
}

async function init() {
  const response = await fetch("content-library.json", { cache: "no-store" });
  state.records = await response.json();
  await loadFieldOptions();
  await handleAuthRedirect();
  await refreshSupabaseSession();
  $("#showLogin").addEventListener("click", () => showMode("login"));
  $("#showRegister").addEventListener("click", () => showMode("register"));
  $("#registerForm").addEventListener("submit", register);
  $("#loginForm").addEventListener("submit", login);
  $("#logoutButton").addEventListener("click", logout);
  $("#prefectureSelect").addEventListener("change", () => {
    populateCities();
    populateWards();
  });
  $("#citySelect").addEventListener("change", populateWards);
  $("#queryForm").addEventListener("submit", handleStructuredQuery);
  $("#backToList").addEventListener("click", closeDetail);
  $("#closeImage").addEventListener("click", closeImage);
  $("#imageDialog").addEventListener("click", (event) => {
    if (event.target.id === "imageDialog") closeImage();
  });
  $("#prevPage").addEventListener("click", () => {
    state.page = Math.max(1, state.page - 1);
    renderLatest();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  $("#nextPage").addEventListener("click", () => {
    state.page += 1;
    renderLatest();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  populateCities();
  populateWards();
  render();
}

init().catch((error) => {
  $("#latestList").innerHTML = `<div class="empty">数据加载失败：${escapeHtml(error.message)}</div>`;
});

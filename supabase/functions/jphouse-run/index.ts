import { isQueryOwnedByUser } from "./authorization.mjs";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

type QueryRow = {
  id: string;
  query_key: string;
  prefecture: string;
  city: string;
  ward: string;
  asset_type: string;
  year: number;
  month: number;
  owner_user_id?: string | null;
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...CORS_HEADERS,
      "Content-Type": "application/json",
    },
  });
}

function env(name: string) {
  return Deno.env.get(name) || "";
}

function serviceKey() {
  const jphouse = env("JPHOUSE_SERVICE_ROLE_KEY");
  if (jphouse) return jphouse;
  const legacy = env("SUPABASE_SERVICE_ROLE_KEY");
  if (legacy) return legacy;
  const secretKeys = env("SUPABASE_SECRET_KEYS");
  if (!secretKeys) return "";
  try {
    const parsed = JSON.parse(secretKeys);
    return parsed.service_role || parsed.secret || Object.values(parsed)[0] || "";
  } catch {
    return "";
  }
}

function publishableKey() {
  const legacy = env("SUPABASE_ANON_KEY");
  if (legacy) return legacy;
  const keys = env("SUPABASE_PUBLISHABLE_KEYS");
  if (!keys) return "";
  try {
    const parsed = JSON.parse(keys);
    return parsed.anon || parsed.publishable || Object.values(parsed)[0] || "";
  } catch {
    return "";
  }
}

async function rest(path: string, init: RequestInit = {}) {
  const key = serviceKey();
  const response = await fetch(`${env("SUPABASE_URL")}/rest/v1${path}`, {
    ...init,
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
      ...(init.headers || {}),
    },
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) throw new Error(`${response.status}: ${text}`);
  return body;
}

async function currentUser(authHeader: string) {
  const token = authHeader.replace(/^Bearer\s+/i, "");
  if (!token) return null;
  const response = await fetch(`${env("SUPABASE_URL")}/auth/v1/user`, {
    headers: {
      apikey: publishableKey() || serviceKey(),
      Authorization: `Bearer ${token}`,
    },
  });
  if (!response.ok) return null;
  return response.json();
}

function areaTitle(query: QueryRow) {
  return [query.prefecture, query.city, query.ward || ""].join("").replace("全部区", "");
}

function factor(query: QueryRow) {
  const area = areaTitle(query);
  let value = 0.78;
  if (area.includes("东京都")) value = 1.75;
  else if (area.includes("大阪府")) value = 1.18;
  else if (area.includes("神奈川县")) value = 1.08;
  else if (["京都府", "兵库县", "爱知县", "福冈县"].some((name) => area.includes(name))) value = 1.0;
  if (["港区", "中央区", "千代田区", "涩谷区", "新宿区", "品川区", "西区", "北区"].some((name) => area.includes(name))) value *= 1.18;
  if (query.asset_type === "塔楼") value *= 1.12;
  if (query.asset_type === "一户建") value *= 0.92;
  return value;
}

function rentRow(layout: string, area: number, rentMan: number) {
  const unit = (rentMan * 10000) / area;
  return {
    layout,
    area: `约${area - 3}–${area + 3}㎡`,
    amount_jpy: `${rentMan.toFixed(1)}万日元/月`,
    amount_rmb: `≈${(rentMan * 0.0423).toFixed(2)}万RMB/月`,
    unit_jpy: `约${Math.round(unit).toLocaleString("ja-JP")}日元/㎡/月`,
    unit_rmb: `≈${Math.round(unit * 0.0423)}RMB/㎡/月`,
  };
}

function saleRow(layout: string, area: number, priceMan: number) {
  const unit = priceMan / area;
  return {
    layout,
    area: `约${area - 3}–${area + 3}㎡`,
    amount_jpy: `约${priceMan.toLocaleString("ja-JP")}万日元`,
    amount_rmb: `≈${Math.round(priceMan * 0.0423).toLocaleString("ja-JP")}万RMB`,
    unit_jpy: `约${unit.toFixed(1)}万日元/㎡`,
    unit_rmb: `≈${(unit * 0.0423).toFixed(1)}万RMB/㎡`,
  };
}

function ratioLine(rental: any[], sale: any[]) {
  return rental.map((rent, index) => {
    const rentMan = Number(String(rent.amount_jpy).split("万")[0]);
    const priceMan = Number(String(sale[index].amount_jpy).replace(/[^0-9]/g, ""));
    return `${rent.layout}｜约${((rentMan * 12 / priceMan) * 100).toFixed(2)}%`;
  }).join("｜");
}

function rowsForQuery(query: QueryRow, f: number) {
  if (query.asset_type === "一户建") {
    const sizes = [
      { label: "80㎡左右", area: 80, rent: 18.5, saleUnit: 72 },
      { label: "110㎡左右", area: 110, rent: 24.5, saleUnit: 68 },
      { label: "140㎡左右", area: 140, rent: 31.5, saleUnit: 64 },
    ];
    return {
      rental: sizes.map((row) => rentRow(row.label, row.area, Math.round(row.rent * f * 10) / 10)),
      sale: sizes.map((row) => saleRow(row.label, row.area, Math.round(row.saleUnit * f * row.area))),
      explain: "一户建不按 1LDK/2LDK/3LDK 拆，这里按建筑面积段看：80㎡、110㎡、140㎡左右。",
    };
  }
  return {
    rental: [
      rentRow("1LDK", 42, Math.round(11.8 * f * 10) / 10),
      rentRow("2LDK", 62, Math.round(17.6 * f * 10) / 10),
      rentRow("3LDK", 82, Math.round(24.2 * f * 10) / 10),
    ],
    sale: [
      saleRow("1LDK", 42, Math.round(105 * f * 42)),
      saleRow("2LDK", 62, Math.round(110 * f * 62)),
      saleRow("3LDK", 82, Math.round(116 * f * 82)),
    ],
    explain: "LDK=客厅+餐厅+厨房，前面的数字=卧室数量；塔楼/公寓按 1LDK、2LDK、3LDK 并列看。",
  };
}

function isStaleDetachedHouseReport(query: QueryRow, report: any) {
  if (query.asset_type !== "一户建") return false;
  const rows = [...(report?.rental || []), ...(report?.sale || [])];
  return rows.some((row) => /LDK/i.test(String(row?.layout || "")));
}

function reportFromQuery(query: QueryRow) {
  const area = areaTitle(query) || "日本";
  const f = factor(query);
  const monthText = `${query.year}年${query.month}月`;
  const { rental, sale, explain } = rowsForQuery(query, f);
  const title = `${area}${query.asset_type}，租还是买？`;
  const slug = `jphouse_edge_${crypto.randomUUID().slice(0, 8)}`;
  const summary = {
    title: "总而言之",
    line: ratioLine(rental, sale),
    note: "算法：月租×12÷买房估算价。云端 JPHOUSE 先生成数据报告，图片后续再补。",
  };
  const markdown = [
    `# ${title}｜${monthText}`,
    "",
    "## 区域说明",
    `${area}，这次由 Supabase Edge Function 按 JPHOUSE 估算模型生成。`,
    "后续接入实时采集源后，同条件查询可以升级成真实采集数据。",
    explain,
    "",
    "## 汇率",
    "汇率按发布当天约算：100日元≈4.23RMB。",
    "",
    "## 租房子",
    ...rental.map((row) => `${row.layout}｜${row.area}｜${row.amount_jpy}≈${row.amount_rmb.replace("≈", "")}｜${row.unit_jpy}≈${row.unit_rmb.replace("≈", "")}`),
    "",
    "## 买房子",
    ...sale.map((row) => `${row.layout}｜${row.area}｜${row.amount_jpy}≈${row.amount_rmb.replace("≈", "")}｜${row.unit_jpy}≈${row.unit_rmb.replace("≈", "")}`),
    "",
    `## ${summary.title}`,
    summary.line,
    summary.note,
  ].join("\n");
  return {
    slug,
    title,
    publish_month: monthText,
    markdown,
    xhs_content: markdown,
    rental,
    sale,
    summary,
    images: [],
    data_sources: [
      { name: "Supabase Edge Function", url: "edge://jphouse-run", usage: "云端按查询条件生成 JPHOUSE 数据报告" },
      { name: "JPHOUSE estimation model", url: "local://jphouse-estimation", usage: "房型、面积、租金、买卖单价估算" },
    ],
    raw_record: { query, generated_by: "supabase-edge-function" },
  };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS_HEADERS });
  if (req.method !== "POST") return jsonResponse({ error: "POST only" }, 405);
  try {
    const user = await currentUser(req.headers.get("Authorization") || "");
    if (!user?.id) return jsonResponse({ error: "未登录或登录已过期" }, 401);

    const body = await req.json().catch(() => ({}));
    const queryId = body.query_id || "";
    const queryKey = body.query_key || "";
    if (!queryId && !queryKey) return jsonResponse({ error: "缺少 query_id 或 query_key" }, 400);

    const filter = queryId ? `id=eq.${encodeURIComponent(queryId)}` : `query_key=eq.${encodeURIComponent(queryKey)}`;
    const queries = await rest(`/queries?select=*&${filter}&limit=1`);
    const query = queries?.[0] as QueryRow | undefined;
    if (!query) return jsonResponse({ error: "查询记录不存在" }, 404);
    if (!isQueryOwnedByUser(query, user.id)) {
      return jsonResponse({ error: "查询记录不存在" }, 404);
    }

    const existing = await rest(`/property_reports?select=*&query_key=eq.${encodeURIComponent(query.query_key)}&limit=1`);
    if (existing?.[0] && !isStaleDetachedHouseReport(query, existing[0])) {
      await rest(`/queries?id=eq.${encodeURIComponent(query.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "completed" }),
      });
      return jsonResponse({ status: "cached", report: existing[0] });
    }

    let jobs = await rest(`/generation_jobs?select=*&query_id=eq.${encodeURIComponent(query.id)}&order=created_at.desc&limit=1`);
    let job = jobs?.[0];
    if (!job) {
      const created = await rest("/generation_jobs", {
        method: "POST",
        body: JSON.stringify({ query_id: query.id, status: "running", progress: 15, current_step: "云端 JPHOUSE 开始执行" }),
      });
      job = created?.[0];
    } else {
      await rest(`/generation_jobs?id=eq.${encodeURIComponent(job.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "running", progress: 15, current_step: "云端 JPHOUSE 开始执行", error_message: null }),
      });
    }
    await rest(`/queries?id=eq.${encodeURIComponent(query.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "running" }),
    });

    const report = reportFromQuery(query);
    const saved = await rest("/property_reports?on_conflict=query_key", {
      method: "POST",
      headers: { Prefer: "resolution=merge-duplicates,return=representation" },
      body: JSON.stringify({
        query_id: query.id,
        query_key: query.query_key,
        ...report,
      }),
    });

    await rest(`/queries?id=eq.${encodeURIComponent(query.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "completed", markdown_title: `# ${report.title}｜${report.publish_month}`, xhs_draft: report.markdown }),
    });
    if (job?.id) {
      await rest(`/generation_jobs?id=eq.${encodeURIComponent(job.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "completed", progress: 100, current_step: "完成", error_message: null }),
      });
    }
    return jsonResponse({ status: "completed", report: saved?.[0] || report });
  } catch (error) {
    return jsonResponse({ error: String(error?.message || error) }, 500);
  }
});

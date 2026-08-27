import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");

const SOURCES = {
  prefectures: "https://raw.githubusercontent.com/nojimage/local-gov-code-jp/master/prefectures.json",
  cities: "https://raw.githubusercontent.com/nojimage/local-gov-code-jp/master/cities.json",
  wards: "https://raw.githubusercontent.com/nojimage/local-gov-code-jp/master/wards.json",
};

const CHAR_MAP = new Map(
  Object.entries({
    県: "县",
    東: "东",
    廣: "广",
    広: "广",
    徳: "德",
    島: "岛",
    鳥: "鸟",
    愛: "爱",
    長: "长",
    児: "儿",
    濱: "滨",
    浜: "滨",
    澤: "泽",
    沢: "泽",
    龜: "龟",
    亀: "龟",
    龍: "龙",
    竜: "龙",
    櫻: "樱",
    桜: "樱",
    鹽: "盐",
    塩: "盐",
    豐: "丰",
    豊: "丰",
    飯: "饭",
    繩: "绳",
    縄: "绳",
    沖: "冲",
    岡: "冈",
    瀬: "濑",
    藤: "藤",
    會: "会",
    館: "馆",
    駒: "驹",
    國: "国",
    国: "国",
    關: "关",
    関: "关",
    園: "园",
    戸: "户",
    澁: "涩",
    渋: "涩",
    髙: "高",
    萬: "万",
    榮: "荣",
    栄: "荣",
    藝: "艺",
    賀: "贺",
    圓: "圆",
    條: "条",
    条: "条",
    與: "与",
    与: "与",
    戰: "战",
    戦: "战",
    讀: "读",
    読: "读",
    稻: "稻",
    稲: "稻",
    淺: "浅",
    浅: "浅",
    淨: "净",
    浄: "净",
    劍: "剑",
    剣: "剑",
    鄉: "乡",
    郷: "乡",
    壽: "寿",
    寿: "寿",
    齋: "斋",
    斎: "斋",
    齊: "齐",
    廳: "厅",
    庁: "厅",
    縣: "县",
    驛: "驿",
    駅: "驿",
    邊: "边",
    辺: "边",
    檜: "桧",
    惠: "惠",
    恵: "惠",
  }),
);

function zh(name) {
  return String(name || "")
    .split("")
    .map((char) => CHAR_MAP.get(char) || char)
    .join("");
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

function uniqueSorted(items) {
  const seen = new Set();
  return items.filter((item) => {
    const key = JSON.stringify(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function uniqueSqlRows(rows) {
  const seen = new Set();
  return rows.filter((item) => {
    const match = item.match(/^\('((?:''|[^'])*)', '((?:''|[^'])*)', '((?:''|[^'])*)'/);
    const key = match ? `${match[1]}\u0000${match[2]}\u0000${match[3]}` : item;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function sqlValue(value) {
  return `'${String(value ?? "").replaceAll("'", "''")}'`;
}

function row(optionType, parentValue, value, label, sortOrder) {
  return `(${sqlValue(optionType)}, ${sqlValue(parentValue)}, ${sqlValue(value)}, ${sqlValue(label || value)}, ${Number(sortOrder)}, true)`;
}

function buildSql(rows) {
  const chunks = [];
  for (let i = 0; i < rows.length; i += 400) chunks.push(rows.slice(i, i + 400));
  return `create table if not exists public.query_field_options (
  id uuid primary key default gen_random_uuid(),
  option_type text not null,
  parent_value text not null default '',
  value text not null,
  label text not null default '',
  sort_order int not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(option_type, parent_value, value)
);

create index if not exists idx_field_options_type_parent
on public.query_field_options(option_type, parent_value, is_active, sort_order);

alter table public.query_field_options enable row level security;

drop policy if exists "public can read field options" on public.query_field_options;
create policy "public can read field options"
on public.query_field_options for select
to anon
using (is_active = true);

${chunks
  .map(
    (chunk) => `insert into public.query_field_options(option_type, parent_value, value, label, sort_order, is_active)
values
  ${chunk.join(",\n  ")}
on conflict(option_type, parent_value, value)
do update set label = excluded.label, sort_order = excluded.sort_order, is_active = true, updated_at = now();`,
  )
  .join("\n\n")}
`;
}

const [prefectures, cities, wards] = await Promise.all([
  fetchJson(SOURCES.prefectures),
  fetchJson(SOURCES.cities),
  fetchJson(SOURCES.wards),
]);

const fieldOptions = {
  prefectures: [],
  cities: {},
  wards: {},
  assetTypes: ["塔楼", "公寓", "一户建"],
  years: ["2024", "2025", "2026", "2027"],
  months: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
};

const sqlRows = [];

for (const [index, pref] of prefectures.entries()) {
  const prefName = zh(pref.pref_name);
  fieldOptions.prefectures.push(prefName);
  sqlRows.push(row("prefecture", "", prefName, prefName, index + 1));
}

const citySort = new Map();
for (const city of cities) {
  const prefName = zh(city.pref_name);
  const cityName = zh(city.city_name);
  if (!fieldOptions.cities[prefName]) {
    fieldOptions.cities[prefName] = [];
    citySort.set(prefName, 0);
  }
  const nextSort = (citySort.get(prefName) || 0) + 1;
  citySort.set(prefName, nextSort);
  fieldOptions.cities[prefName].push(cityName);
  sqlRows.push(row("city", prefName, cityName, cityName, nextSort));
}

const wardSort = new Map();
for (const ward of wards) {
  const prefName = zh(ward.pref_name);
  const cityName = zh(ward.city_name);
  const wardName = zh(ward.ward_name);
  const parent = `${prefName}::${cityName}`;
  if (!fieldOptions.wards[parent]) {
    fieldOptions.wards[parent] = [];
    wardSort.set(parent, 0);
  }
  const nextSort = (wardSort.get(parent) || 0) + 1;
  wardSort.set(parent, nextSort);
  fieldOptions.wards[parent].push(wardName);
  sqlRows.push(row("ward", parent, wardName, wardName, nextSort));
}

for (const [index, assetType] of fieldOptions.assetTypes.entries()) {
  sqlRows.push(row("asset_type", "", assetType, assetType, index + 1));
}
for (const [index, year] of fieldOptions.years.entries()) {
  sqlRows.push(row("year", "", year, year, index + 1));
}
for (const [index, month] of fieldOptions.months.entries()) {
  sqlRows.push(row("month", "", month, `${month}月`, index + 1));
}

fieldOptions.prefectures = uniqueSorted(fieldOptions.prefectures);
for (const key of Object.keys(fieldOptions.cities)) fieldOptions.cities[key] = uniqueSorted(fieldOptions.cities[key]);
for (const key of Object.keys(fieldOptions.wards)) fieldOptions.wards[key] = uniqueSorted(fieldOptions.wards[key]);

await fs.writeFile(path.join(root, "web", "field-options.json"), `${JSON.stringify(fieldOptions, null, 2)}\n`);
const dedupedSqlRows = uniqueSqlRows(sqlRows);
await fs.writeFile(path.join(root, "backend", "sql", "supabase_field_options.sql"), buildSql(dedupedSqlRows));

console.log(
  JSON.stringify(
    {
      prefectures: fieldOptions.prefectures.length,
      cities: Object.values(fieldOptions.cities).reduce((sum, items) => sum + items.length, 0),
      wardCities: Object.keys(fieldOptions.wards).length,
      wards: Object.values(fieldOptions.wards).reduce((sum, items) => sum + items.length, 0),
      sqlRows: dedupedSqlRows.length,
    },
    null,
    2,
  ),
);

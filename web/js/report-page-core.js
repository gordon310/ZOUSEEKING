const REGION_CURRENCY = Object.freeze({ CN: "CNY", TW: "TWD", HK: "HKD", MO: "HKD", SG: "SGD", JP: "JPY" });

function normalizeRegion(value) {
  return String(value || "").trim().toUpperCase();
}

export function inferRegion({ queryRegion = "", language = "", timeZone = "" } = {}) {
  const explicit = normalizeRegion(queryRegion);
  if (REGION_CURRENCY[explicit]) return explicit;
  const locale = String(language || "").toUpperCase();
  for (const region of ["TW", "HK", "MO", "SG", "CN", "JP"]) {
    if (locale.includes(`-${region}`) || locale.endsWith(region)) return region;
  }
  const zone = String(timeZone || "").toUpperCase();
  if (zone.includes("TAIPEI")) return "TW";
  if (zone.includes("HONG_KONG")) return "HK";
  if (zone.includes("MACAU")) return "MO";
  if (zone.includes("SINGAPORE")) return "SG";
  if (zone.includes("TOKYO")) return "JP";
  if (zone.includes("SHANGHAI") || zone.includes("BEIJING")) return "CN";
  return "CN";
}

export function currencyForRegion(region) {
  return REGION_CURRENCY[normalizeRegion(region)] || "CNY";
}

export function selectPrice(prices, productCode, currency) {
  return (Array.isArray(prices) ? prices : []).find(
    (price) => price?.active !== false && price?.available !== false && price?.product_code === productCode && price?.currency === currency,
  ) || null;
}

export function reportAccessState(report) {
  if (report?.metadata?.unlocked === true || report?.unlocked === true || report?.locked === false) return "unlocked";
  return "locked";
}

export { REGION_CURRENCY };

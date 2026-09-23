(function exposeRecordLocation(global) {
  function text(value) {
    return typeof value === "string" ? value.trim() : "";
  }

  // Compatibility parser for old generated records that predate canonical
  // prefecture/city/ward fields. New records must use structured fields.
  function parseLegacyRecordLocation(title) {
    const value = text(title);
    const patterns = [
      { prefix: "东京", prefecture: "东京都", city: "东京23区" },
      { prefix: "大阪", prefecture: "大阪府", city: "大阪市" },
      { prefix: "横滨", prefecture: "神奈川县", city: "横滨市" },
    ];
    const match = patterns.find((item) => value.startsWith(item.prefix));
    if (!match) return { prefecture: "", city: "", ward: "" };
    const rest = value.slice(match.prefix.length);
    let ward = rest
      .replace(/^(?:府|县|市|都)/, "")
      .split(/塔楼|一户建|公寓|房产|，|,|｜|租还是买/)[0]
      .trim();
    if (ward.startsWith(match.city)) ward = ward.slice(match.city.length);
    return { prefecture: match.prefecture, city: match.city, ward };
  }

  function queryFields(record) {
    return record?.raw_record?.query && typeof record.raw_record.query === "object"
      ? record.raw_record.query
      : {};
  }

  function recordLocation(record = {}) {
    const query = queryFields(record);
    const fallback = parseLegacyRecordLocation(record.title);
    const structured = {
      prefecture: text(record.prefecture) || text(query.prefecture),
      city: text(record.city) || text(query.city),
      ward: text(record.ward) || text(query.ward),
      asset_type: text(record.asset_type) || text(query.asset_type) || text(query.assetType),
    };
    return {
      prefecture: structured.prefecture || fallback.prefecture,
      city: structured.city || fallback.city,
      ward: structured.ward || fallback.ward,
      asset_type: structured.asset_type || text(record.assetType) || parseLegacyAssetType(record.title),
    };
  }

  function parseLegacyAssetType(title) {
    const value = text(title);
    if (value.includes("一户建")) return "一户建";
    if (value.includes("塔楼")) return "塔楼";
    if (value.includes("公寓")) return "公寓";
    return value.includes("房产") ? "房产" : "";
  }

  global.ZouRecordLocation = { parseLegacyRecordLocation, recordLocation };
})(typeof window === "undefined" ? globalThis : window);

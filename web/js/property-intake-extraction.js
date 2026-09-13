const NUMBER = "(?:[0-9０-９]{1,3}(?:[.,，．][0-9０-９]{3})+|[0-9０-９]+(?:[.,，．][0-9０-９]+)?)";

function normalizeDigits(value) {
  return value
    .replace(/[０-９]/g, (digit) => String.fromCharCode(digit.charCodeAt(0) - "０".charCodeAt(0) + "0".charCodeAt(0)))
    .replace(/[，,]/g, "")
    .replace(/．/g, ".");
}

function numericValue(value) {
  const number = Number(normalizeDigits(value));
  return Number.isFinite(number) ? number : null;
}

function firstPrice(text) {
  const match = text.match(new RegExp(
    `(?:售价|售價|价格|價格|価格|販売価格|販売額|売価)?\\s*${NUMBER}\\s*(億|万)(?:日元|日圓|円)?|(?:售价|售價|价格|價格|価格|販売価格|販売額|売価)?\\s*${NUMBER}\\s*(?:日元|日圓|円)`,
  ));
  if (!match) return null;
  const amount = numericValue(match[0].match(new RegExp(NUMBER))[0]);
  if (amount === null) return null;
  if (match[1] === "億") return amount * 100000000;
  if (match[1] === "万") return amount * 10000;
  return amount;
}

function firstArea(text) {
  const match = text.match(new RegExp(
    `(?:面积|面積|専有面積|专有面积)?\\s*(${NUMBER})\\s*(?:㎡|m²|m2|平方米|平米|平方(?:米)?)`,
    "i",
  ));
  return match ? numericValue(match[1]) : null;
}

function firstAddress(text, priceMatch, areaMatch) {
  const houseNumber = text.match(/[\p{Script=Han}々ヶー]{1,30}\s*[0-9０-９]+[-－ー][0-9０-９]+(?:[-－ー][0-9０-９]+)+/u);
  if (houseNumber) return houseNumber[0].replace(/\s+/g, "");

  if (!priceMatch && !areaMatch && text.trim()) return text.trim().replace(/[，,。．.]+$/u, "");

  const boundary = [priceMatch?.index, areaMatch?.index].filter((index) => index !== undefined).sort((a, b) => a - b)[0];
  if (boundary === undefined) return null;
  const candidate = text.slice(0, boundary).trim().replace(/[，,、。:：]+$/u, "");
  return candidate && /[\p{Script=Han}々ヶー]/u.test(candidate) ? candidate : null;
}

export function extractPropertyFields(rawText) {
  const text = String(rawText || "").normalize("NFKC").trim();
  if (!text) return {};

  const priceMatch = text.match(new RegExp(
    `(?:售价|售價|价格|價格|価格|販売価格|販売額|売価)?\\s*${NUMBER}\\s*(?:億|万)(?:日元|日圓|円)?|(?:售价|售價|价格|價格|価格|販売価格|販売額|売価)?\\s*${NUMBER}\\s*(?:日元|日圓|円)`,
  ));
  const areaMatch = text.match(new RegExp(
    `(?:面积|面積|専有面積|专有面积)?\\s*${NUMBER}\\s*(?:㎡|m²|m2|平方米|平米|平方(?:米)?)`,
    "i",
  ));
  const fields = {};
  const price = firstPrice(text);
  const area = firstArea(text);
  const address = firstAddress(text, priceMatch, areaMatch);
  if (price !== null) fields.asking_price_jpy = price;
  if (area !== null) fields.area_sqm = area;
  if (address) fields.address = address;
  return fields;
}

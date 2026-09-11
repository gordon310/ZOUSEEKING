const test = require("node:test");
const assert = require("node:assert/strict");

let core;

test.before(async () => {
  core = await import("../../web/js/report-page-core.js");
});

test("infers billing region from explicit query, then locale and timezone", () => {
  assert.equal(core.inferRegion({ queryRegion: "HK", language: "en-US", timeZone: "Asia/Shanghai" }), "HK");
  assert.equal(core.inferRegion({ language: "zh-TW", timeZone: "Asia/Tokyo" }), "TW");
  assert.equal(core.inferRegion({ language: "en-SG", timeZone: "Asia/Singapore" }), "SG");
  assert.equal(core.inferRegion({ language: "ja-JP", timeZone: "Asia/Tokyo" }), "JP");
  assert.equal(core.inferRegion({ language: "en-US", timeZone: "America/Los_Angeles" }), "CN");
});

test("maps regions to currencies without embedding any price", () => {
  assert.equal(core.currencyForRegion("TW"), "TWD");
  assert.equal(core.currencyForRegion("HK"), "HKD");
  assert.equal(core.currencyForRegion("SG"), "SGD");
  assert.equal(core.currencyForRegion("JP"), "JPY");
  assert.equal(core.currencyForRegion("CN"), "CNY");
});

test("selects the backend price for product and currency", () => {
  const prices = [
    { product_code: "risk_report_single", currency: "CNY", amount_minor: 9900, active: true },
    { product_code: "risk_report_single", currency: "JPY", amount_minor: 1900, active: true },
  ];
  assert.deepEqual(core.selectPrice(prices, "risk_report_single", "JPY"), prices[1]);
  assert.equal(core.selectPrice(prices, "risk_report_single", "HKD"), null);
  assert.equal(core.selectPrice([{ ...prices[0], available: false }], "risk_report_single", "CNY"), null);
});

test("trusts only the server report shape for access state", () => {
  assert.equal(core.reportAccessState({ locked: true }), "locked");
  assert.equal(core.reportAccessState({ locked: false, markdown: "full" }), "unlocked");
  assert.equal(core.reportAccessState({ metadata: { unlocked: true } }), "unlocked");
  assert.equal(core.reportAccessState({ metadata: { unlocked: false }, locked: true }), "locked");
});

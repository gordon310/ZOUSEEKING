const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function loadI18n({ language = "en-US", search = "", savedLocale = null } = {}) {
  const source = fs.readFileSync("web/js/i18n.js", "utf8");
  const elements = [];
  const document = {
    documentElement: { lang: "" },
    querySelectorAll() { return elements; },
  };
  const storage = {
    getItem() { return savedLocale; },
    setItem(_key, value) { savedLocale = value; },
  };
  const context = {
    document,
    localStorage: storage,
    location: { search },
    URLSearchParams,
    navigator: { language },
    Intl: { DateTimeFormat: () => ({ resolvedOptions: () => ({ timeZone: "UTC" }) }) },
    window: {},
  };
  vm.runInNewContext(source, context, { filename: "web/js/i18n.js" });
  return context.window.ZouI18n;
}

test("zh-Hant has exactly the zh-CN keys", () => {
  const i18n = loadI18n();
  assert.deepEqual(i18n.keys("zh-Hant"), i18n.keys("zh-CN"));
});

test("all supported locales have the same key set", () => {
  const i18n = loadI18n();
  const expected = i18n.keys("zh-CN");
  for (const locale of ["zh-Hant", "en", "ja"]) {
    assert.deepEqual(i18n.keys(locale), expected, locale);
  }
});

test("zh-Hant keeps the same placeholders as zh-CN", () => {
  const i18n = loadI18n();
  for (const key of i18n.keys("zh-CN")) {
    assert.deepEqual(i18n.placeholders("zh-Hant", key), i18n.placeholders("zh-CN", key), key);
  }
});

test("browser language mapping selects the expected locale", () => {
  assert.equal(loadI18n({ language: "zh-TW" }).detectedLocale, "zh-Hant");
  assert.equal(loadI18n({ language: "zh-HK" }).detectedLocale, "zh-Hant");
  assert.equal(loadI18n({ language: "zh-CN" }).detectedLocale, "zh-CN");
  assert.equal(loadI18n({ language: "zh-SG" }).detectedLocale, "zh-CN");
  assert.equal(loadI18n({ language: "zh-Hans-JP" }).detectedLocale, "zh-CN");
  assert.equal(loadI18n({ language: "zh-Hant-HK" }).detectedLocale, "zh-Hant");
  assert.equal(loadI18n({ language: "ja-JP" }).detectedLocale, "ja");
  assert.equal(loadI18n({ language: "en-US" }).detectedLocale, "en");
  assert.equal(loadI18n({ language: "fr-FR" }).detectedLocale, "en");
});

test("explicit URL locale has priority over saved and browser language", () => {
  assert.equal(loadI18n({ savedLocale: "en", search: "?lang=zh-TW", language: "en-US" }).locale(), "zh-Hant");
  assert.equal(loadI18n({ search: "?lang=zh-TW", language: "en-US" }).locale(), "zh-Hant");
});

test("Taiwan copy uses Taiwan terms for the affected login and intake text", () => {
  const i18n = loadI18n({ language: "zh-TW" });
  assert.equal(i18n.t("account.loginQueryCopy"), "未登入只能看最近 5 條資料。註冊很簡單，別緊張，不查戶口。");
  assert.equal(i18n.t("intake.copy"), "我們幫你整理物件關鍵資料、核對潛在風險與合規資訊，讓你看得更清楚，決策更安心。");
});

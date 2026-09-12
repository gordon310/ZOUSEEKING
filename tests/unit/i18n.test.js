const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const INTAKE_RUNTIME_KEYS = [
  "intake.fileTypeInvalid",
  "intake.fileEmpty",
  "intake.fileTooLarge",
  "intake.photoTypeInvalid",
  "intake.photoEmpty",
  "intake.photoTooLarge",
  "intake.filesSelected",
  "intake.photosSelected",
  "intake.recognizedEmptyRuntime",
  "intake.completedCountRuntime",
  "intake.purposeUnselected",
  "intake.materialsUnsubmitted",
  "intake.projectNameDuplicateAddress",
  "intake.projectNameTaken",
  "intake.projectNameRequired",
  "intake.materialsSubmitted",
  "intake.demoMaterialsSubmitted",
  "intake.materialSubmitFailed",
  "intake.sessionExpired",
  "intake.confirmFieldRequired",
  "intake.savingFields",
  "intake.demoPreviewGenerated",
  "intake.previewGenerated",
  "intake.previewFailed",
  "intake.demoProjectSaved",
  "intake.demoProjectSavedStatus",
  "intake.loginRequiredToSave",
  "intake.projectSaved",
  "intake.projectSaveFailed",
  "intake.openMenu",
  "intake.closeMenu",
  "intake.projectNameHelpRuntime",
  "intake.demoModeEnabled",
  "intake.sessionRestored",
  "intake.sessionMissingAssetType",
  "intake.locationOptionsLoading",
  "intake.locationOptionsRetry",
  "intake.previewDimensionIdentity",
  "intake.previewDimensionPriceCost",
  "intake.previewDimensionYield",
  "intake.previewDimensionBuildingManagement",
  "intake.previewDimensionLegalTransaction",
  "intake.previewDimensionSourceTrust",
  "intake.previewStatusComplete",
  "intake.previewStatusPartial",
  "intake.previewStatusEmpty",
  "intake.previewStatusInsufficientData",
  "intake.previewAssetTypeApartment",
  "intake.previewAssetTypeTower",
  "intake.previewAssetTypeDetachedHouse",
  "intake.previewAssetTypeOther",
  "intake.previewMeterLabel",
  "intake.previewDimensionSummary",
  "intake.previewMissingCritical",
  "intake.previewAssetType",
  "intake.previewCostNoteInsufficientInput",
  "intake.previewCostNoteEstimated",
  "intake.previewCostNotePending",
  "intake.previewEstimatedAmount",
  "intake.previewPendingInput",
  "intake.previewNeedsInput",
  "intake.previewEstimatedTotal",
  "intake.previewRiskSummary",
  "intake.previewNoRisk",
  "intake.previewRiskItem",
  "intake.previewComparableAmount",
  "intake.previewPeriodUnknown",
  "intake.previewComparableRow",
  "intake.previewComparableInsufficient",
];

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
    window: { addEventListener() {} },
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

test("password guidance is eight characters in every supported locale", () => {
  const expected = {
    "zh-CN": "至少 8 位",
    "zh-Hant": "至少 8 位",
    en: "At least 8 characters",
    ja: "8文字以上",
  };
  for (const [locale, placeholder] of Object.entries(expected)) {
    const i18n = loadI18n({ search: `?lang=${locale}` });
    assert.equal(i18n.t("account.passwordShortPlaceholder"), placeholder, locale);
    assert.match(i18n.t("account.resetPasswordInvalid"), /8/);
    assert.doesNotMatch(i18n.t("account.resetPasswordInvalid"), /12–128|12～128/);
  }
});

test("report, workspace and admin dynamic copy is localized with matching placeholders", () => {
  const i18n = loadI18n();
  const keys = [
    "report.unlockWithPrice",
    "workspace.versionCount",
    "workspace.readonlyVersion",
    "admin.orderTotals",
    "admin.kpiToday",
  ];
  for (const key of keys) {
    for (const locale of ["zh-CN", "zh-Hant", "en", "ja"]) {
      assert.ok(i18n.keys(locale).includes(key), `${locale}: ${key}`);
      assert.deepEqual(i18n.placeholders(locale, key), i18n.placeholders("zh-CN", key), `${locale}: ${key}`);
    }
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

test("traditional conversion covers known simplified characters", () => {
  const i18n = loadI18n({ language: "zh-TW" });
  assert.equal(i18n.toTraditional("选择照片后会自动尝试读取 EXIF 位置"), "選擇照片後會自動嘗試讀取 EXIF 位置");
});

test("traditional conversion keeps 系 as 系 except for explicit relationship wording", () => {
  const i18n = loadI18n({ language: "zh-TW" });
  assert.equal(i18n.toTraditional("系统只返回可用的区域级候选地址"), "系統只返回可用的區域級候選地址");
  assert.equal(i18n.toTraditional("关系和后台"), "關係和後台");
});

test("preview data labels are localized for every supported locale", () => {
  const expected = {
    "zh-CN": "中介手续费",
    "zh-Hant": "仲介手續費",
    en: "Brokerage fee",
    ja: "仲介手数料",
  };
  for (const locale of Object.keys(expected)) {
    const i18n = loadI18n({ search: `?lang=${locale}` });
    assert.equal(i18n.previewText("中介手续费"), expected[locale], locale);
  }
});

test("all zh-CN dictionary copy converts known simplified characters", () => {
  const i18n = loadI18n({ language: "zh-CN" });
  const knownSimplifiedCharacters = ["尝"];
  for (const key of i18n.keys("zh-CN")) {
    const converted = i18n.toTraditional(i18n.t(key));
    for (const character of knownSimplifiedCharacters) {
      assert.equal(converted.includes(character), false, `${key}: ${character}`);
    }
  }
});

test("runtime intake copy has four-locale keys and no direct Chinese status literals", () => {
  const i18n = loadI18n();
  for (const locale of ["zh-CN", "zh-Hant", "en", "ja"]) {
    for (const key of INTAKE_RUNTIME_KEYS) assert.ok(i18n.keys(locale).includes(key), `${locale}: ${key}`);
  }
  const source = fs.readFileSync("web/js/property-intake.js", "utf8");
  for (const literal of [
    "请选择自住或投资出租。",
    "请选择物件类型（公寓、塔楼、一户建等），否则无法判断。",
    "请先填写物件链接或说明，或上传资料/物件照片。",
    "正在创建临时分析项目，资料会在 24 小时后到期。",
    "临时项目已失效，请重新开始。",
  ]) assert.equal(source.includes(`setStatus("${literal}"`), false, literal);
});

test("location loading exposes loading, retry and validated payload behavior", () => {
  const source = fs.readFileSync("web/js/property-intake.js", "utf8");
  assert.match(source, /locationOptionsLoading/);
  assert.match(source, /locationOptionsRetry/);
  assert.match(source, /addEventListener\("click", \(\) => loadLocationFields\(\)\)/);
  assert.match(source, /Array\.isArray\(payload\.prefectures\)/);
  assert.match(source, /payload\.cities[\s\S]*typeof payload\.cities !== "object"/);
  assert.match(source, /payload\.wards[\s\S]*typeof payload\.wards !== "object"/);
});

test("global runtime error notice is localized, dismissible and deduplicated", () => {
  const i18n = loadI18n();
  for (const locale of ["zh-CN", "zh-Hant", "en", "ja"]) {
    for (const key of ["global.runtimeError", "global.dismissError"]) {
      assert.ok(i18n.keys(locale).includes(key), `${locale}: ${key}`);
    }
  }
  const source = fs.readFileSync("web/js/i18n.js", "utf8");
  assert.match(source, /unhandledrejection/);
  assert.match(source, /window\.addEventListener\("error"/);
  assert.match(source, /dataset\.runtimeErrorKey/);
  assert.match(source, /remove\(\)/);
});

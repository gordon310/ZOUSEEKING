import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const intake = fs.readFileSync("web/js/property-intake.js", "utf8");
const i18n = fs.readFileSync("web/js/i18n.js", "utf8");

test("property type and location are sufficient to start intake without materials", () => {
  assert.doesNotMatch(intake, /if \(!source && !files\.length && !photos\.length\)/);
  assert.match(intake, /const locationError = validateLocationFields\(\);/);
});

test("optional material copy is synchronized across supported intake locales", () => {
  assert.match(i18n, /"intake\.sourceRequired": "请选择物件类型和地区后即可继续，链接、说明、文件和照片均为可选。"/);
  assert.match(i18n, /"intake\.sourceRequired": "Select a property type and location to continue; links, descriptions, files and photos are optional\."/);
  assert.match(i18n, /"intake\.sourceRequired": "物件タイプと地域を選択すれば続行できます。リンク、説明、ファイル、写真は任意です。"/);
});

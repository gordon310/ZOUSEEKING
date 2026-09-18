const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

let location;

function assertLocation(actual, expected) {
  assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected);
}

test.before(async () => {
  const window = {};
  vm.runInNewContext(fs.readFileSync("web/js/record-location.js", "utf8"), { window });
  location = window.ZouRecordLocation;
});

test("uses structured location and asset type fields without reading the title", () => {
  assertLocation(
    location.recordLocation({
      title: "脏标题：请勿从这里推导地区",
      prefecture: "东京都",
      city: "东京23区",
      ward: "港区",
      asset_type: "塔楼",
    }),
    { prefecture: "东京都", city: "东京23区", ward: "港区", asset_type: "塔楼" },
  );
});

test("reads structured fields nested in the stored report query", () => {
  assertLocation(
    location.recordLocation({
      title: "完全不匹配的标题",
      raw_record: { query: { prefecture: "大阪府", city: "大阪市", ward: "北区", asset_type: "一户建" } },
    }),
    { prefecture: "大阪府", city: "大阪市", ward: "北区", asset_type: "一户建" },
  );
});

test("explicitly parses legacy title only for records missing structured fields", () => {
  assertLocation(
    location.recordLocation({ title: "东京港区塔楼，租还是买？", asset_type: "塔楼" }),
    { prefecture: "东京都", city: "东京23区", ward: "港区", asset_type: "塔楼" },
  );
  assertLocation(
    location.recordLocation({ title: "大阪府大阪市北区一户建，租还是买？" }),
    { prefecture: "大阪府", city: "大阪市", ward: "北区", asset_type: "一户建" },
  );
});

test("keeps legacy fallback behavior for dirty or unknown titles", () => {
  assertLocation(
    location.recordLocation({ title: "脏标题", asset_type: "公寓" }),
    { prefecture: "", city: "", ward: "", asset_type: "公寓" },
  );
});

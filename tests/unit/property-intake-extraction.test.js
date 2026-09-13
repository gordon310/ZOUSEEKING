const test = require("node:test");
const assert = require("node:assert/strict");

let extraction;

test.before(async () => {
  extraction = await import("../../web/js/property-intake-extraction.js");
});

test("extracts the reported Chinese price, area, and address", () => {
  assert.deepEqual(
    extraction.extractPropertyFields("林寺2-5-22 售价 5200万日元 面积110平方"),
    {
      asking_price_jpy: 52000000,
      area_sqm: 110,
      address: "林寺2-5-22",
    },
  );
});

test("normalizes Japanese and formatted price/area units", () => {
  assert.equal(extraction.extractPropertyFields("価格1.2億円").asking_price_jpy, 120000000);
  assert.equal(extraction.extractPropertyFields("販売価格5200万円").asking_price_jpy, 52000000);
  assert.equal(extraction.extractPropertyFields("52,000,000日元").asking_price_jpy, 52000000);
  assert.equal(extraction.extractPropertyFields("専有面積110㎡").area_sqm, 110);
  assert.equal(extraction.extractPropertyFields("面积110平方米").area_sqm, 110);
  assert.equal(extraction.extractPropertyFields("110平米").area_sqm, 110);
});

test("leaves unrecognized fields empty instead of borrowing unrelated numbers", () => {
  assert.deepEqual(extraction.extractPropertyFields("林寺2-5-22，只有楼层39层"), {
    address: "林寺2-5-22",
  });
  assert.deepEqual(extraction.extractPropertyFields("大阪府大阪市北区梅田"), {
    address: "大阪府大阪市北区梅田",
  });
});

test("uses the first explicit occurrence when a field is repeated", () => {
  assert.deepEqual(
    extraction.extractPropertyFields("售价5200万日元，后来改为5300万日元，面积110㎡后补120㎡"),
    { asking_price_jpy: 52000000, area_sqm: 110 },
  );
});

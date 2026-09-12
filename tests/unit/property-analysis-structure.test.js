const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const htmlPath = path.resolve(__dirname, "../../web/property-analysis.html");
const html = fs.readFileSync(htmlPath, "utf8");

function assertBalancedTags(source, tagNames) {
  const tags = new Set(tagNames);
  const counts = new Map(tagNames.map((tagName) => [tagName, { open: 0, close: 0 }]));
  const tokenPattern = /<!--[\s\S]*?-->|<\/?([a-z][a-z0-9:-]*)(?:\s[^<>]*?)?\/?\s*>/gi;
  let match;
  let rawTextTag = null;

  while ((match = tokenPattern.exec(source))) {
    const token = match[0];
    const tagName = match[1]?.toLowerCase();
    if (token.startsWith("<!--") || !tagName || !tags.has(tagName)) continue;
    if (rawTextTag) {
      if (token.startsWith("</") && tagName === rawTextTag) rawTextTag = null;
      continue;
    }
    if (token.startsWith("</")) {
      counts.get(tagName).close += 1;
    } else if (!token.endsWith("/>") && !["input", "img", "meta", "link", "br", "hr", "source"].includes(tagName)) {
      counts.get(tagName).open += 1;
      if (["script", "style"].includes(tagName)) rawTextTag = tagName;
    }
  }

  for (const [tagName, { open, close }] of counts) {
    assert.equal(close, open, `${tagName}: ${open} opening tags, ${close} closing tags`);
  }
}

test("property-analysis HTML keeps structural tags balanced", () => {
  assertBalancedTags(html, ["section", "div", "form", "ul", "ol", "li", "dl", "dt", "dd"]);
});

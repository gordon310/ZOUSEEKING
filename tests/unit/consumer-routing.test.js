const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), "utf8");

test("consumer home is an independent C-end entry page", () => {
  const html = read("web/consumer-home.html");
  assert.match(html, /<title[^>]*>[^<]*小象避坑/);
  assert.match(html, /property-analysis\.html/);
  assert.match(html, /profile\.html\?role=consumer#accountPanel/);
});

test("consumer-owned navigation does not use the B-end index page", () => {
  const consumerHtml = [
    "web/consumer-home.html",
    "web/property-analysis.html",
    "web/projects.html",
    "web/project.html",
    "web/report.html",
  ].map(read).join("\n");
  const consumerScripts = ["web/js/property-intake.js", "web/js/profile-role.js"].map(read).join("\n");

  assert.doesNotMatch(consumerHtml, /(?:href|src)=["']index\.html(?:["'#?])/);
  assert.doesNotMatch(consumerHtml, /href=["']mypage\.html(?:["'#?])/);
  assert.doesNotMatch(consumerScripts, /(?:location\.(?:href|assign|replace)|href\s*=)[^;\n]*index\.html/);
});

test("C-end nginx server redirects direct index access and never falls back to B-end index", () => {
  const nginx = read("deploy/nginx/default.conf");
  const cServer = nginx.match(/server_name zoubeacon\.app[\s\S]*?\n}\n\nserver \{/)?.[0] || "";

  assert.match(cServer, /location = \/index\.html \{\s*return 302 \/;\s*\}/);
  assert.match(cServer, /location = \/ \{\s*try_files \/consumer-home\.html =404;\s*\}/);
  assert.match(cServer, /try_files \$uri \$uri\/ \/consumer-home\.html;/);
  assert.doesNotMatch(cServer, /try_files \$uri \$uri\/ \/index\.html;/);
});

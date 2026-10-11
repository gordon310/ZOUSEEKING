const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), "utf8");

test("consumer home is an independent C-end entry page", () => {
  const html = read("web/consumer-home.html");
  assert.match(html, /<title[^>]*>[^<]*小象避坑/);
  assert.match(html, /consumer-profile\.html#accountPanel/);
  assert.doesNotMatch(html, /href=["']property-analysis\.html/);
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

test("consumer navigation uses a dedicated account page and never exposes B-end routes", () => {
  const consumerAccountPath = path.join(root, "web/consumer-profile.html");
  assert.equal(fs.existsSync(consumerAccountPath), true, "consumer account page must exist");

  const consumerHtml = [
    "web/consumer-home.html",
    "web/consumer-profile.html",
    "web/property-analysis.html",
    "web/projects.html",
    "web/project.html",
    "web/report.html",
  ].map(read).join("\n");
  const blockedPaths = new Set([
    "/index.html",
    "/data-query.html",
    "/analysis.html",
    "/mypage.html",
    "/profile.html",
    "/organization.html",
    "/billing.html",
    "/usage.html",
    "/subscriptions.html",
    "/exports.html",
    "/service-tasks.html",
    "/admin.html",
    "/ui-review.html",
    "/reset-password.html",
  ]);

  assert.match(consumerHtml, /consumer-profile\.html/);
  const hrefs = Array.from(consumerHtml.matchAll(/href=["']([^"']+)/g), (match) => match[1]);
  for (const href of hrefs) {
    const target = new URL(href, "https://zoubeacon.app");
    assert.notEqual(target.hostname, "platform.zoubeacon.com", `B-end host leaked through ${href}`);
    assert.equal(blockedPaths.has(target.pathname), false, `B-end path leaked through ${href}`);
  }

  const worker = read("web-source/sw.js");
  assert.match(worker, /"\.\/consumer-profile\.html"/);
  for (const target of ["index", "mypage", "profile"]) assert.doesNotMatch(worker, new RegExp(`"\.\/${target}\\.html"`));
});

test("C-end nginx server redirects direct index access and never falls back to B-end index", () => {
  const nginx = read("deploy/nginx/default.conf");
  const cServer = nginx.match(/server_name zoubeacon\.app[\s\S]*?\n}\n\nserver \{/)?.[0] || "";

  assert.match(cServer, /location = \/index\.html \{\s*return 302 \/;\s*\}/);
  assert.match(cServer, /location = \/ \{\s*try_files \/consumer-home\.html =404;\s*\}/);
  assert.match(cServer, /try_files \$uri \$uri\/ \/consumer-home\.html;/);
  assert.doesNotMatch(cServer, /try_files \$uri \$uri\/ \/index\.html;/);
  assert.match(cServer, /location ~ \^\/\(\?:data-query\|analysis\|mypage\|profile\|organization\|billing\|usage\|subscriptions\|exports\|service-tasks\|admin\|invite\|ui-review\|reset-password\)\\\.html\$ \{\s*return 404;\s*\}/);
});

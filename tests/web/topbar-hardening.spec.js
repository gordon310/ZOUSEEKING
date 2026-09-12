const { test, expect } = require("@playwright/test");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const businessPages = [
  "index.html",
  "data-query.html",
  "analysis.html",
  "mypage.html",
  "profile.html",
  "organization.html",
  "billing.html",
  "usage.html",
  "subscriptions.html",
  "exports.html",
  "service-tasks.html",
];

const viewports = [
  [1440, 900],
  [1194, 834],
  [1024, 768],
  [834, 1194],
  [768, 1024],
  [480, 800],
  [390, 844],
];

const fileBase = pathToFileURL(path.resolve(__dirname, "../../web")).href;

async function gotoBusinessPage(page, route) {
  await page.goto(process.env.TOPBAR_TEST_FILE === "1" ? `${fileBase}/${route}` : `/${route}`);
}

async function assertTopbarGeometry(page, route, fontScale = false) {
  await gotoBusinessPage(page, route);
  if (fontScale) {
    await page.addStyleTag({
      content: `
        html { font-size: 150% !important; }
        .topbar-brand-copy strong,
        .topbar-brand-copy small,
        .topbar-links a { font-size: 150% !important; }
      `,
    });
  }

  const result = await page.evaluate(() => {
    const topbar = document.querySelector(".topbar");
    const brand = document.querySelector(".topbar-brand");
    const links = document.querySelector(".topbar-links");
    const mark = document.querySelector(".topbar-brand .brand-mark");
    const intersects = (first, second) => !(
      first.right <= second.left ||
      first.left >= second.right ||
      first.bottom <= second.top ||
      first.top >= second.bottom
    );
    const rect = (element) => element.getBoundingClientRect().toJSON();

    return {
      flexWrap: getComputedStyle(topbar).flexWrap,
      brand: rect(brand),
      links: rect(links),
      mark: rect(mark),
      topbar: rect(topbar),
      overlap: intersects(brand.getBoundingClientRect(), links.getBoundingClientRect()),
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  });

  expect(result.flexWrap, `${route} ${fontScale ? "font-scaled" : "base"}`).toBe("wrap");
  expect(result.overlap, `${route} ${fontScale ? "font-scaled" : "base"}`).toBe(false);
  expect(result.horizontalOverflow, `${route} ${fontScale ? "font-scaled" : "base"}`).toBe(false);
  expect(result.mark.left, `${route} logo left edge`).toBeGreaterThanOrEqual(result.topbar.left);
  expect(result.mark.right, `${route} logo right edge`).toBeLessThanOrEqual(result.topbar.right);
}

test("B 端共享 topbar 在多视口下品牌与导航不相交", async ({ page }) => {
  for (const route of businessPages) {
    for (const [width, height] of viewports) {
      await page.setViewportSize({ width, height });
      await assertTopbarGeometry(page, route);
    }
  }
});

test("B 端共享 topbar 在根字号 150% 模拟下仍不相交", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of businessPages) {
    await assertTopbarGeometry(page, route, true);
  }
});

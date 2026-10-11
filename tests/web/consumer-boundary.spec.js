const { test, expect } = require("@playwright/test");

const B_END_TARGET = /(?:platform\.zoubeacon\.com|\/(?:index|data-query|analysis|mypage|profile|organization|billing|usage|subscriptions|exports|service-tasks|admin|ui-review)\.html)/;

async function expectOnlyConsumerNavigation(page) {
  const hrefs = await page.locator("a[href]").evaluateAll((links) => links.map((link) => link.href));
  expect(hrefs.some((href) => B_END_TARGET.test(href))).toBe(false);
}

test("consumer account page renders C-end navigation before scripts can rewrite it", async ({ page }) => {
  const response = await page.goto("/consumer-profile.html");

  expect(response.status()).toBe(200);
  await expect(page.locator(".topbar-brand-copy strong")).toHaveText("小象避坑");
  await expect(page.locator(".topbar-brand-copy small")).toHaveText("ZOUBEACON");
  await expectOnlyConsumerNavigation(page);
});

test("consumer analysis page has no B-end or internal review entry", async ({ page }) => {
  await page.goto("/property-analysis.html?demo=1");

  await expect(page.locator('a[href="https://platform.zoubeacon.com/"]')).toHaveCount(0);
  await expect(page.locator("#reviewLink")).toHaveCount(0);
  await expectOnlyConsumerNavigation(page);
});

test("consumer password reset page keeps the C-end identity and navigation", async ({ page }) => {
  const response = await page.goto("/consumer-reset-password.html");

  expect(response.status()).toBe(200);
  await expect(page.locator(".topbar-brand-copy strong")).toHaveText("小象避坑");
  await expect(page.locator(".topbar-brand-copy small")).toHaveText("ZOUBEACON");
  await expectOnlyConsumerNavigation(page);
});

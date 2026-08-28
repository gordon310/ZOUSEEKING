const { test, expect } = require("@playwright/test");

test("free preview renders the report-style preview and its paid teaser", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/project.html?demo=1&state=preview");

  const freeReport = page.locator("#freeReportContent");
  await expect(page).toHaveTitle("项目工作台｜小象避坑 ZOUBEACON");
  await expect(freeReport).toBeVisible();
  await expect(page.locator("#reportContent")).toBeHidden();
  await expect(freeReport.getByRole("heading", { name: "先看清资料状态，再决定是否继续" })).toBeVisible();
  await expect(freeReport.getByText("收费完整版会继续展开什么？")).toBeVisible();
  await expect(freeReport.getByRole("button", { name: "注册并保存项目" })).toBeVisible();
  await expect(freeReport).toContainText("synthetic_fixture");

  const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(hasHorizontalOverflow).toBe(false);
});

test("paid report renders all 11 chapters and hides the free preview", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/project.html?demo=1&state=completed");

  const paidReport = page.locator("#reportContent");
  await expect(paidReport).toBeVisible();
  await expect(page.locator("#freeReportContent")).toBeHidden();
  await expect(page.locator("#projectStatus")).toHaveText("完整报告");
  await expect(paidReport.getByRole("heading", { level: 3 })).toHaveCount(11);
  await expect(paidReport.getByRole("heading", { name: "投资收益分析" })).toBeVisible();
  await expect(paidReport.getByRole("heading", { name: "方法、版本信息和免责声明" })).toBeVisible();
  await expect(paidReport).toContainText("数据类别 synthetic_fixture");
});

test("review state selector switches between free and paid report layouts", async ({ page }) => {
  await page.goto("/project.html?demo=1&state=preview");
  await page.locator("#stateSelector").selectOption("completed");

  await expect(page.locator("#projectStatus")).toHaveText("完整报告");
  await expect(page.locator("#freeReportContent")).toBeHidden();
  await expect(page.locator("#reportContent")).toBeVisible();

  await page.locator("#stateSelector").selectOption("preview");
  await expect(page.locator("#projectStatus")).toHaveText("免费预览");
  await expect(page.locator("#freeReportContent")).toBeVisible();
  await expect(page.locator("#reportContent")).toBeHidden();
});

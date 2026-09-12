const { test, expect } = require("@playwright/test");

test("intake step sections are sibling sections in the parsed DOM", async ({ page }) => {
  await page.goto("/property-analysis.html");

  const structure = await page.locator("#submitStep, #confirmStep, #previewStep").evaluateAll((sections) => ({
    ids: sections.map((section) => section.id),
    parentId: sections[0]?.parentElement?.id,
    parentMatches: sections.every((section) => section.parentElement === sections[0]?.parentElement),
    distinct: new Set(sections.map((section) => section.parentElement)).size === 1,
  }));

  expect(structure.ids).toEqual(["submitStep", "confirmStep", "previewStep"]);
  expect(structure.parentId).toBe("flow-content");
  expect(structure.parentMatches).toBe(true);
  expect(structure.distinct).toBe(true);
});

test("location selects live in submit step and confirm step shows a read-only summary", async ({ page }) => {
  await page.goto("/property-analysis.html");

  await expect(page.locator("#submitStep #prefecture")).toHaveCount(1);
  await expect(page.locator("#submitStep #city")).toHaveCount(1);
  await expect(page.locator("#submitStep #ward")).toHaveCount(1);
  await expect(page.locator("#confirmStep #prefecture, #confirmStep #city, #confirmStep #ward")).toHaveCount(0);
  await expect(page.locator("#confirmStep [data-testid='location-summary']")).toHaveCount(1);
  await expect(page.locator("#submitStep #prefecture, #submitStep #city, #submitStep #ward")).toHaveAttribute("required", "");
});

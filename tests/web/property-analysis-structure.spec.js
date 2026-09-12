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

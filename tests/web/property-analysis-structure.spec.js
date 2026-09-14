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
  for (const id of ["prefecture", "city", "ward"]) {
    await expect(page.locator(`#submitStep #${id}`)).toHaveAttribute("required", "");
  }
});

test("confirm step has visible fields after materials are organized", async ({ page }) => {
  await page.goto("/property-analysis.html?demo=1");

  await page.getByLabel("物件类型 / 房型").selectOption("apartment");
  await page.getByLabel("都道府县").selectOption("东京都");
  await page.getByLabel("市").selectOption("港区");
  await page.getByLabel("区").selectOption("__not_subdivided__");
  await page.getByLabel("物件链接或说明").fill("港区的物件");
  await page.getByRole("button", { name: "开始整理资料" }).click();

  const state = await page.locator("#confirmStep").evaluate((section) => ({
    hidden: section.hidden,
    offsetHeight: section.offsetHeight,
    visibleControls: [...section.querySelectorAll("input, select, button")].filter((control) => {
      const style = getComputedStyle(control);
      const rect = control.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
    }).length,
    previewButton: (() => {
      const button = section.querySelector("#previewButton");
      const rect = button.getBoundingClientRect();
      const style = getComputedStyle(button);
      return {
        visible: !button.hidden && style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0,
        enabled: !button.disabled,
      };
    })(),
  }));

  expect(state.hidden).toBe(false);
  expect(state.offsetHeight).toBeGreaterThan(0);
  expect(state.visibleControls).toBeGreaterThan(0);
  expect(state.previewButton).toEqual({ visible: true, enabled: true });
});

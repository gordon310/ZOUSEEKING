const { test, expect } = require("@playwright/test");

for (const path of ["/index.html", "/admin.html"]) {
  test(`${path} blocks real network writes in the phase-one release`, async ({ page }) => {
    let externalWrites = 0;
    let sameOriginPrivateReads = 0;
    await page.route("https://operations.test/**", async (route) => {
      externalWrites += 1;
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });
    await page.route("**/api/private-records", async (route) => {
      sameOriginPrivateReads += 1;
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });

    await page.goto(path);
    const result = await page.evaluate(async () => {
      try {
        await window.fetch("https://operations.test/rest/v1/private_records", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ real: true }),
        });
        return { blocked: false, message: "" };
      } catch (error) {
        return { blocked: true, message: String(error?.message || error) };
      }
    });

    expect(result.blocked).toBe(true);
    expect(result.message).toContain("disabled");
    expect(externalWrites).toBe(0);

    const privateRead = await page.evaluate(async () => {
      try {
        await window.fetch("/api/private-records");
        return { blocked: false, message: "" };
      } catch (error) {
        return { blocked: true, message: String(error?.message || error) };
      }
    });
    expect(privateRead.blocked).toBe(true);
    expect(privateRead.message).toContain("disabled");
    expect(sameOriginPrivateReads).toBe(0);
  });
}

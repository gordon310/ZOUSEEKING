const { test, expect } = require("@playwright/test");

const ONE_PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

test("photo EXIF location request prefills the query form and has no AI entry", async ({ page }) => {
  let requests = 0;
  await page.addInitScript(() => {
    window.ZOUSEEKING_API_BASE_URL = "http://api.test";
    window.localStorage.setItem(
      "zou_house_session",
      JSON.stringify({ provider: "supabase", accessToken: "test-access-token", username: "用户 A" }),
    );
  });
  await page.route("http://api.test/api/recognition", async (route) => {
    requests += 1;
    expect(route.request().postDataJSON()).toEqual({ image: expect.any(String), resolve_location_only: true });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        location: { prefecture: "大阪府", city: "大阪市", ward: "北区" },
        location_reason: null,
        listing: null,
      }),
    });
  });

  await page.goto("/property-analysis.html");
  await expect(page.locator("#recognitionButton")).toHaveCount(0);
  await expect(page.getByText("识别挂牌候选")).toHaveCount(0);
  await expect(page.getByText("OpenAI")).toHaveCount(0);
  await page.setInputFiles("#recognitionImage", { name: "property.png", mimeType: "image/png", buffer: ONE_PIXEL_PNG });
  await expect.poll(() => requests).toBe(1);
  await expect(page.locator("#recognitionLocationStatus")).toContainText("大阪市");
  await expect(page.locator("#recognitionLocationStatus")).toContainText("北区");
});

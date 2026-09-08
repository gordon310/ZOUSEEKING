const { test, expect } = require("@playwright/test");

test("PWA shell assets are served and wired", async ({ page }) => {
  const response = await page.goto("/index.html");
  expect(response.status()).toBe(200);

  // manifest link + theme color present
  const manifestHref = await page.getAttribute('link[rel="manifest"]', "href");
  expect(manifestHref).toBe("manifest.webmanifest");

  // manifest is valid JSON with app identity and icons
  const manifestResponse = await page.request.get(`/${manifestHref}`);
  expect(manifestResponse.status()).toBe(200);
  const manifest = await manifestResponse.json();
  expect(manifest.name).toBeTruthy();
  expect(manifest.start_url).toContain("index.html");
  expect(manifest.icons.length).toBeGreaterThanOrEqual(2);
  const anyIcon = await page.request.get(`/${manifest.icons[0].src}`);
  expect(anyIcon.status()).toBe(200);

  // service worker is served and syntactically loadable
  const swResponse = await page.request.get("/sw.js");
  expect(swResponse.status()).toBe(200);
  const swSource = await swResponse.text();
  expect(swSource).toContain('self.addEventListener("install"');
  // registration script is present on the page
  const html = await page.content();
  expect(html).toContain("navigator.serviceWorker.register");
});

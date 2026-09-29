const { test, expect } = require("@playwright/test");

// The manifest is consumed by consumer pages, so its text must speak the
// consumer brand; the B-side product name must not leak into it.
const C_SIDE_BRAND = "小象避坑";

async function manifestOf(page) {
  const manifestHref = await page.getAttribute('link[rel="manifest"]', "href");
  expect(manifestHref).toMatch(/^manifest\.webmanifest(?:\?v=\d{8}-r\d+)?$/);
  const response = await page.request.get(`/${manifestHref}`);
  expect(response.status()).toBe(200);
  return response.json();
}

test("PWA shell assets are served and wired", async ({ page }) => {
  const response = await page.goto("/index.html");
  expect(response.status()).toBe(200);

  // manifest link + theme color present
  const manifestHref = await page.getAttribute('link[rel="manifest"]', "href");
  expect(manifestHref).toMatch(/^manifest\.webmanifest(?:\?v=\d{8}-r\d+)?$/);

  // manifest is valid JSON with app identity and icons
  const manifestResponse = await page.request.get(`/${manifestHref}`);
  expect(manifestResponse.status()).toBe(200);
  const manifest = await manifestOf(page);
  expect(manifest.name).toBeTruthy();
  // start_url is the site root: on the consumer origin "/" serves the consumer
  // home page, so an installed app opens there instead of at a redirect.
  expect(manifest.start_url).toMatch(/^\.?\/?$/);
  expect(manifest.icons.length).toBeGreaterThanOrEqual(2);
  const anyIcon = await page.request.get(`/${manifest.icons[0].src}`);
  expect(anyIcon.status()).toBe(200);

  // service worker is served and syntactically loadable
  const swResponse = await page.request.get("/sw.js");
  expect(swResponse.status()).toBe(200);
  const swSource = await swResponse.text();
  expect(swSource).toContain('self.addEventListener("install"');
  // registration script is present on the page
  const pwaSrc = await page.locator('script[src*="js/pwa.js"]').getAttribute("src");
  const pwaResponse = await page.request.get(`/${pwaSrc}`);
  expect(pwaResponse.status()).toBe(200);
  expect(await pwaResponse.text()).toContain("navigator.serviceWorker.register");
});

test("consumer home page is installable and carries the consumer identity", async ({ page }) => {
  // Addressed by name rather than as "/": a plain static server resolves "/" to
  // index.html, while production nginx resolves it to consumer-home.html, so
  // testing "/" would exercise a different file locally than in production.
  // consumer-home.html is the page a visitor lands on, and therefore the one
  // whose manifest the browser reads on "add to home screen"; it previously
  // linked no manifest and loaded no registration script, which made the
  // consumer home page the one page that could not be installed.
  const response = await page.goto("/consumer-home.html");
  expect(response.status()).toBe(200);

  const manifest = await manifestOf(page);
  expect(manifest.name).toContain(C_SIDE_BRAND);
  expect(manifest.short_name).toContain(C_SIDE_BRAND);
  // The B-side product name belongs to the other product; it must not leak here.
  expect(manifest.name).not.toContain("小象数据");
  expect(manifest.description).not.toContain("小象数据");

  const pwaSrc = await page.locator('script[src*="js/pwa.js"]').getAttribute("src");
  expect(pwaSrc).toBeTruthy();
  const pwaResponse = await page.request.get(`/${pwaSrc}`);
  expect(pwaResponse.status()).toBe(200);

  const swResponse = await page.request.get("/sw.js");
  expect(swResponse.status()).toBe(200);
});

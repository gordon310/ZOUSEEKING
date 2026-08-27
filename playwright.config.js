const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "tests/web",
  timeout: 15_000,
  use: {
    baseURL: "http://127.0.0.1:8787",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "python3 -m http.server 8787 -d web",
    url: "http://127.0.0.1:8787/property-analysis.html",
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
});

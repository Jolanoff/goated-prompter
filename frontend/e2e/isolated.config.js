import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5191",
    browserName: "chromium",
    channel: process.env.PLAYWRIGHT_CHANNEL,
    headless: true,
  },
  webServer: [
    {
      command: "python ../tests/local_ui_server.py",
      env: { GOATED_UI_TEST_PORT: "8191" },
      cwd: "..",
      url: "http://127.0.0.1:8191/api/bootstrap",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --config e2e/vite.config.js",
      cwd: "..",
      url: "http://127.0.0.1:5191",
      reuseExistingServer: false,
    },
  ],
});

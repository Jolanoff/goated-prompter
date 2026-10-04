import { defineConfig } from "@playwright/test";

const apiPort = process.env.GOATED_UI_TEST_PORT || "8190";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5173",
    browserName: "chromium",
    channel: process.env.PLAYWRIGHT_CHANNEL,
    headless: true,
  },
  webServer: [
    {
      command: "python ../tests/local_ui_server.py",
      url: `http://127.0.0.1:${apiPort}/api/bootstrap`,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
    },
  ],
});

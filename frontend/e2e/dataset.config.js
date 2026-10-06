import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "dataset*.spec.js",
  outputDir: "../../quality-artifacts/test/dataset-browser",
  timeout: 30000,
  workers: 1,
  use: { baseURL: "http://127.0.0.1:8196", browserName: "chromium", headless: true },
  webServer: { command: "python ../tests/local_ui_server.py", cwd: "..", env: { GOATED_UI_TEST_PORT: "8196" },
    url: "http://127.0.0.1:8196/api/bootstrap", reuseExistingServer: false },
});

import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const python = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export default defineConfig({
  testDir: "../built-e2e",
  testMatch: "understanding.spec.js",
  outputDir: "../../quality-artifacts/test/understanding-browser",
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8192",
    browserName: "chromium",
    channel: process.env.PLAYWRIGHT_CHANNEL,
    headless: true,
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `"${python}" "${path.join(root, "tests/understanding_ui_replay.py")}"`,
    cwd: "..",
    url: "http://127.0.0.1:8192/api/bootstrap",
    reuseExistingServer: false,
  },
});

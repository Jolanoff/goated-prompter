import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const python = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const port = process.env.GOATED_UI_TEST_PORT || "8193";
const task = process.env.GOATED_TEST_TASK_KEY || "vocabulary-ui";
if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(task)) throw new Error("Invalid test task key");

export default defineConfig({
  testDir: ".", testMatch: ["vocabulary.spec.js", "vocabulary-creator.spec.js"], workers: 1, timeout: 30000,
  outputDir: `../../quality-artifacts/temp/${task}/browser/vocabulary`,
  use: { baseURL: `http://127.0.0.1:${port}`, browserName: "chromium", channel: process.env.PLAYWRIGHT_CHANNEL,
    headless: true, screenshot: "only-on-failure" },
  webServer: process.env.GOATED_UI_EXTERNAL === "1" ? undefined : {
    command: `"${python}" "${path.join(root, "tests/local_ui_server.py")}"`, cwd: root,
    env: { GOATED_UI_TEST_PORT: port, GOATED_TEST_TASK_KEY: task },
    url: `http://127.0.0.1:${port}/api/bootstrap`, reuseExistingServer: false,
  },
});

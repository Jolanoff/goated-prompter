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
      command: `python -c "import os,runpy,tempfile; from pathlib import Path; data=tempfile.TemporaryDirectory(); os.environ['GOATED_PROMPTER_USER_DIR']=str(Path(data.name)/'directors'); ns=runpy.run_path('../tests/local_ui_server.py'); ns['web'].run_app(ns['create_app'](port=8191, config_loader=lambda: {'backend': 'mock'}, settings_path=Path(data.name)/'settings.json', service_factory=ns['DelayedMockService']), host='127.0.0.1', port=8191)"`,
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

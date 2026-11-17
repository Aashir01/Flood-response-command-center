import { defineConfig, devices } from '@playwright/test';
const PORT = 4173;
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  // One mock Brain process holds the scenario, so tests run one at a time.
  workers: 1,
  retries: 0,
  timeout: 90_000,
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure' },
  projects: [
    { name: 'mock', testMatch: /.*\.spec\.ts$/, use: { ...devices['Desktop Chrome'] } },
    // `npm run shots`: screenshots for docs/screenshots (not part of the smoke suite).
    { name: 'shots', testMatch: /.*\.shots\.ts$/, use: { ...devices['Desktop Chrome'], deviceScaleFactor: 1 } },
  ],
  webServer: {
    // Serves the static export from out/ plus the mock Brain under /api on one origin.
    command: `node mock-brain/server.mjs --port ${PORT} --static out`,
    url: `http://127.0.0.1:${PORT}/api/healthz`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});

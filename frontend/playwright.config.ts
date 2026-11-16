import { defineConfig, devices } from '@playwright/test';

const PORT = 4173;
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure' },
  projects: [{ name: 'mock', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // Serves the static export from out/ plus the mock Brain under /api on one origin.
    command: `node mock-brain/server.mjs --port ${PORT} --static out`,
    url: `http://127.0.0.1:${PORT}/api/healthz`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
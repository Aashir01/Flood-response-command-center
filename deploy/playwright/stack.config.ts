// Playwright config for the stack project (deploy/playwright/stack.spec.ts). No web server: the
// Compose stack is already running behind the gateway at STACK_URL.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: /stack\.spec\.ts$/,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  reporter: [['list']],
  use: {
    baseURL: process.env.STACK_URL ?? 'http://127.0.0.1:8080',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
});

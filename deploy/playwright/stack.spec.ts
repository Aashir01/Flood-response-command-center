// Browser leg of the stack smoke test (deploy design 9.1, 11; DEP-R5.1, DEP-R10, DEP-P6).
// Runs against the real Compose stack through the gateway, not the mock Brain. CI copies this
// directory into frontend/ (so @playwright/test resolves from frontend/node_modules) and runs
//   STACK_URL=http://127.0.0.1:8080 npx playwright test -c tests-stack/stack.config.ts
// Checks: zero CSP violations and console errors on /en/ and /ur/, the map canvas renders under
// the CSP (MapLibre workers from blob:), every browser request stays on the gateway origin, and
// the default demo briefing completes with five sections.
import { expect, test, type Page } from '@playwright/test';

const ORIGIN = new URL(process.env.STACK_URL ?? 'http://127.0.0.1:8080').origin;

function watch(page: Page) {
  const problems: string[] = [];
  page.on('console', (msg) => {
    const text = msg.text();
    if (msg.type() === 'error' || /Content Security Policy|Refused to/i.test(text)) problems.push(`console: ${text}`);
  });
  page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`));
  page.on('request', (req) => {
    const url = req.url();
    if (url.startsWith('data:') || url.startsWith('blob:')) return;
    if (new URL(url).origin !== ORIGIN) problems.push(`off-origin request: ${url}`);
  });
  return problems;
}

async function skipAwakening(page: Page) {
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('awakening')).toHaveCount(0, { timeout: 8000 });
}

for (const lang of ['en', 'ur'] as const) {
  test(`/${lang}/ loads with no CSP violation, no console error, same-origin only`, async ({ page }) => {
    const problems = watch(page);
    const health = page.waitForResponse((r) => r.url().endsWith('/api/organs'), { timeout: 20_000 });
    const res = await page.goto(`/${lang}/`);
    expect(res?.status()).toBe(200);
    expect(res?.headers()['content-security-policy']).toContain("default-src 'self'");
    expect((await health).status()).toBe(200);
    await skipAwakening(page);
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(1500);
    expect(problems).toEqual([]);
  });
}

test('default demo briefing completes through the gateway', async ({ page }) => {
  const problems = watch(page);
  await page.goto('/en/');
  await page.waitForResponse((r) => r.url().endsWith('/api/organs'), { timeout: 20_000 }).catch(() => undefined);
  await skipAwakening(page);
  await page.getByTestId('run').click();
  await expect(page.getByTestId('confidence')).toBeVisible({ timeout: 120_000 });
  for (const id of ['extent', 'forecast', 'guidance', 'allocation', 'caveats'])
    await expect(page.locator(`#card-${id}`)).toHaveAttribute('data-panel-state', /success|partial|unavailable|error/);
  await expect(page.locator('#card-forecast')).toContainText('Modeled (GloFAS)');
  expect(problems).toEqual([]);
});
